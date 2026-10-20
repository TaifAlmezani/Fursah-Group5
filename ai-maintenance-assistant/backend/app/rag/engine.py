"""Offline semantic retrieval with real cosine scores and curated SOP applicability."""
import hashlib
import json
import logging
from pathlib import Path
import re
from threading import RLock
from typing import Sequence
import uuid
from app.config import settings
from app.schemas import ProcedureChunk

logger = logging.getLogger(__name__)
DEVICE_NAMES = {"air_conditioner":"المكيف", "printer":"الطابعة", "plumbing":"السباكة", "electrical":"المعدات الكهربائية", "heater":"السخان", "other":"الجهاز"}
SYMPTOM_TEXT = {"water_leak":"تسرب المياه", "abnormal_noise":"صوت غير طبيعي واهتزاز", "not_working":"عدم التشغيل الجهاز لا يعمل", "low_cooling":"ضعف التبريد", "paper_jam":"انحشار الورق", "power_issue":"مشكلة مصدر الطاقة الكهربائية", "overheating":"ارتفاع الحرارة"}
SIGNAL_TEXT = {"electrical_risk":"تعرض معدات كهربائية للمياه وخطر كهربائي", "fire_or_smoke":"حريق أو دخان", "flooding":"فيضان مياه كثيف", "exposed_wires":"أسلاك كهربائية مكشوفة"}
_lock = RLock()
_encoder = _encoder_key = None
_indexes = {}


class RAGUnavailableError(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(f"Local RAG unavailable: {reason}")


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _catalog(path):
    root = Path(path).resolve()
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    if catalog.get("version") != 1 or not isinstance(catalog.get("documents"), dict):
        raise ValueError("Unsupported SOP catalog")
    for name in catalog["documents"]:
        if Path(name).name != name or not name.endswith(".md") or not (root / name).resolve().is_relative_to(root):
            raise ValueError("SOP source must stay inside the knowledge directory")
    return root, catalog


def corpus_hash(path):
    root, catalog = _catalog(path)
    digest = hashlib.sha256((root / "catalog.json").read_bytes())
    for name in sorted(catalog["documents"]):
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def load_and_split_documents(knowledge_path: str) -> list[dict]:
    root, catalog = _catalog(knowledge_path)
    documents = []
    for name, source in sorted(catalog["documents"].items()):
        if source.get("source_status") != "project_reference":
            continue
        asset = source["asset_type"]
        if asset not in DEVICE_NAMES:
            raise ValueError("Unknown SOP asset type")
        text = (root / name).read_text(encoding="utf-8").strip()
        title = text.splitlines()[0].lstrip("# ")
        seen = set()
        for part in re.split(r"^##\s+", text, flags=re.MULTILINE)[1:]:
            heading, _, body = part.partition("\n")
            heading, body = heading.strip(), body.strip()
            if heading in seen:
                raise ValueError("Duplicate SOP section")
            seen.add(heading)
            tags = source.get("sections", {}).get(heading)
            if not tags or not body:
                continue
            symptoms, signals, scope = tags.get("symptoms", []), tags.get("safety_signals", []), tags.get("scope")
            if not set(symptoms).issubset(SYMPTOM_TEXT) or not set(signals).issubset(SIGNAL_TEXT) or scope not in {"device", "shared_safety"}:
                raise ValueError("Invalid SOP applicability")
            content = f"## {heading}\n{body}"
            documents.append({"content":content, "embedding_text":f"{DEVICE_NAMES[asset]} | {title}\n{content}",
                "metadata":{"procedure_id":f"{Path(name).stem}:{hashlib.sha256(content.encode()).hexdigest()[:16]}",
                    "source":name, "section":heading, "source_sha256":file_hash(root / name), "asset_type":asset,
                    "scope":scope, "symptoms":symptoms, "safety_signals":signals, "source_status":"project_reference"}})
        if set(source.get("sections", {})) - seen:
            raise ValueError(f"Catalogued section missing in {name}")
    return documents


def _model_key():
    root = Path(settings.embedding_model_path).resolve()
    try:
        data = (root / "embedding-source.json").read_bytes()
        record = json.loads(data)
        if record["model"] != settings.embedding_model or record["revision"] != settings.embedding_revision:
            raise ValueError("Embedding revision mismatch")
        stat = (root / "model.safetensors").stat()
        return str(root), hashlib.sha256(data).hexdigest(), stat.st_size, stat.st_mtime_ns
    except Exception as exc:
        raise RAGUnavailableError("embedding_files_missing_or_invalid") from exc


def get_embedder():
    global _encoder, _encoder_key
    with _lock:
        key = _model_key()
        if _encoder is not None and _encoder_key == key:
            return _encoder
        try:
            root = Path(key[0])
            record = json.loads((root / "embedding-source.json").read_text(encoding="utf-8"))
            if file_hash(root / "model.safetensors") != record["weights_sha256"]:
                raise ValueError("Embedding weights checksum mismatch")
            import torch
            from sentence_transformers import SentenceTransformer
            torch.set_num_threads(settings.rag_cpu_threads)
            model = SentenceTransformer(str(root), device="cpu", local_files_only=True, trust_remote_code=False)
            model.eval()
            _encoder, _encoder_key = model, key
            return model
        except Exception as exc:
            _encoder = _encoder_key = None
            logger.exception("Embedding loading failed")
            raise RAGUnavailableError("embedding_load_failed") from exc


def _encode(texts):
    import numpy as np
    import faiss
    vectors = np.asarray(get_embedder().encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False), dtype="float32")
    if vectors.ndim != 2 or len(vectors) != len(texts) or not np.isfinite(vectors).all() or (np.linalg.norm(vectors, axis=1) == 0).any():
        raise RAGUnavailableError("invalid_embedding_vectors")
    faiss.normalize_L2(vectors)
    return np.ascontiguousarray(vectors)


def build_rag_index(knowledge_path=None, vectorstore_path=None):
    import faiss
    knowledge = knowledge_path or settings.knowledge_path
    store = Path(vectorstore_path or settings.vectorstore_path)
    documents = load_and_split_documents(knowledge)
    if not documents:
        raise ValueError("No substantive catalogued SOP sections")
    fingerprint = corpus_hash(knowledge)
    encoder = get_embedder()
    if getattr(encoder, "tokenizer", None):
        for doc in documents:
            if len(encoder.tokenizer(doc["embedding_text"])["input_ids"]) > encoder.max_seq_length:
                raise ValueError(f"SOP section exceeds embedding context; split it: {doc['metadata']['procedure_id']}")
    vectors = _encode([d["embedding_text"] for d in documents])
    faiss.omp_set_num_threads(settings.rag_cpu_threads)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    generation = uuid.uuid4().hex
    target = store / "generations" / generation
    target.mkdir(parents=True, exist_ok=False)
    faiss.write_index(index, str(target / "index.faiss"))
    manifest = {"format_version":2, "generation":generation, "embedding_model":settings.embedding_model,
        "embedding_revision":settings.embedding_revision, "dimension":vectors.shape[1], "metric":"cosine_normalized_inner_product",
        "count":len(documents), "corpus_sha256":fingerprint, "index_sha256":file_hash(target / "index.faiss"), "documents":documents}
    (target / "manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    pointer = {"generation":generation, "manifest_sha256":file_hash(target / "manifest.json")}
    temp = store / f"current-{generation}.tmp"
    temp.write_text(json.dumps(pointer),encoding="utf-8")
    temp.replace(store / "current.json")
    return len(documents)


def _load_index(vectorstore_path=None):
    import faiss
    store = Path(vectorstore_path or settings.vectorstore_path).resolve()
    try:
        pointer = json.loads((store / "current.json").read_text(encoding="utf-8"))
        generation = pointer["generation"]
        if not re.fullmatch(r"[0-9a-f]{32}", generation):
            raise ValueError("Invalid generation")
        target = store / "generations" / generation
        if file_hash(target / "manifest.json") != pointer["manifest_sha256"]:
            raise ValueError("Manifest checksum mismatch")
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        if manifest["format_version"] != 2 or manifest["embedding_model"] != settings.embedding_model or manifest["embedding_revision"] != settings.embedding_revision:
            raise RAGUnavailableError("index_model_mismatch")
        if manifest["corpus_sha256"] != corpus_hash(settings.knowledge_path):
            raise RAGUnavailableError("index_stale")
        if manifest["documents"] != load_and_split_documents(settings.knowledge_path) or file_hash(target / "index.faiss") != manifest["index_sha256"]:
            raise ValueError("Index does not match its sources")
        key = (str(store), generation, pointer["manifest_sha256"])
        with _lock:
            if key not in _indexes:
                index = faiss.read_index(str(target / "index.faiss"))
                if index.ntotal != manifest["count"] or index.ntotal != len(manifest["documents"]) or index.d != manifest["dimension"] or index.metric_type != faiss.METRIC_INNER_PRODUCT:
                    raise ValueError("Index shape or metric mismatch")
                _indexes.clear()
                _indexes[key] = index
            return _indexes[key], manifest
    except RAGUnavailableError:
        raise
    except FileNotFoundError as exc:
        raise RAGUnavailableError("index_missing") from exc
    except Exception as exc:
        raise RAGUnavailableError("index_invalid") from exc


def initialize_rag():
    try:
        _load_index()
        _encode(["اختبار البحث في إجراءات الصيانة"])
        return True
    except Exception:
        logger.exception("RAG initialization failed; run scripts/setup_rag.py")
        return False


def get_rag_status():
    try:
        _, manifest = _load_index()
        loaded = _encoder is not None and _encoder_key == _model_key()
        return {"ready":loaded, "status":"ready" if loaded else "embedding_not_loaded", "engine":"faiss_cosine",
            "embedding_model":settings.embedding_model, "embedding_revision":settings.embedding_revision,
            "generation":manifest["generation"], "count":manifest["count"]}
    except RAGUnavailableError as exc:
        return {"ready":False, "status":exc.reason, "engine":"faiss_cosine"}


def retrieve_procedures(asset_type: str, symptoms: Sequence[str] = (), safety_signals: Sequence[str] = (),
        vectorstore_path=None, top_k=None, min_score=None) -> list[ProcedureChunk]:
    limit = settings.rag_top_k if top_k is None else top_k
    threshold = settings.rag_min_score if min_score is None else min_score
    if limit < 0 or not 0 <= threshold <= 1:
        raise ValueError("Invalid RAG top_k or min_score")
    if limit == 0:
        return []
    index, manifest = _load_index(vectorstore_path)
    hazards, reported = set(safety_signals), set(symptoms)
    candidates = set()
    for idx, doc in enumerate(manifest["documents"]):
        m = doc["metadata"]
        eligible = (bool(hazards.intersection(m["safety_signals"])) and (m["asset_type"] == asset_type or m["scope"] == "shared_safety")) if hazards else (m["asset_type"] == asset_type and m["scope"] == "device" and bool(reported.intersection(m["symptoms"])))
        if eligible:
            candidates.add(idx)
    labels = [SIGNAL_TEXT[s] for s in safety_signals if s in SIGNAL_TEXT] if hazards else [SYMPTOM_TEXT[s] for s in symptoms if s in SYMPTOM_TEXT]
    if not candidates or not labels:
        return []
    with _lock:
        vectors = _encode([f"{DEVICE_NAMES.get(asset_type, 'الجهاز')} — {label}" for label in labels])
        if vectors.shape[1] != index.d:
            raise RAGUnavailableError("embedding_dimension_mismatch")
        scores, ids = index.search(vectors, index.ntotal)
    best = {}
    for row_scores, row_ids in zip(scores, ids):
        for score, idx in zip(row_scores, row_ids):
            if int(idx) in candidates:
                best[int(idx)] = max(float(score), best.get(int(idx), -1.0))
    results = []
    for idx, score in sorted(best.items(), key=lambda item:(-item[1], item[0])):
        if score < threshold:
            continue
        doc = manifest["documents"][idx]
        m = doc["metadata"]
        results.append(ProcedureChunk(source=m["source"], content=doc["content"], score=round(score,6),
            procedure_id=m["procedure_id"], section=m["section"], asset_type=m["asset_type"],
            symptoms=m["symptoms"], safety_signals=m["safety_signals"], source_sha256=m["source_sha256"], index_generation=manifest["generation"]))
        if len(results) == limit:
            break
    return results
