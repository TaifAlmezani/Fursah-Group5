"""Download pinned local embeddings, build FAISS, and verify actual semantic retrieval."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings
from app.rag.engine import build_rag_index, file_hash, get_rag_status, retrieve_procedures

WEIGHTS_SHA256 = "eaa086f0ffee582aeb45b36e34cdd1fe2d6de2bef61f8a559a1bbc9bd955917b"
FILES = ["model.safetensors", "config.json", "config_sentence_transformers.json", "modules.json",
    "sentence_bert_config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "1_Pooling/config.json"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", default=settings.embedding_model_path)
    parser.add_argument("--index-dir", default=settings.vectorstore_path)
    parser.add_argument("--knowledge-dir", default=settings.knowledge_path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--download-only", action="store_true")
    modes.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    settings.embedding_model_path = str(Path(args.model_dir).resolve())
    settings.vectorstore_path = str(Path(args.index_dir).resolve())
    settings.knowledge_path = str(Path(args.knowledge_dir).resolve())
    root = Path(settings.embedding_model_path)
    if not args.build_only:
        from huggingface_hub import snapshot_download
        snapshot_download(settings.embedding_model, revision=settings.embedding_revision, local_dir=root,
            max_workers=2, allow_patterns=FILES)
    for name in FILES:
        if not (root / name).is_file():
            raise RuntimeError(f"Missing embedding file: {name}")
    if file_hash(root / "model.safetensors") != WEIGHTS_SHA256:
        raise RuntimeError("Official embedding weights SHA256 mismatch")
    (root / "embedding-source.json").write_text(json.dumps({"model":settings.embedding_model,
        "revision":settings.embedding_revision, "weights_sha256":WEIGHTS_SHA256}),encoding="utf-8")
    if args.download_only:
        print("Embedding download verified. Build and verify retrieval with --build-only.",flush=True)
        return 0
    print("Building actual local embeddings and FAISS index...",flush=True)
    count = build_rag_index()
    cases = [("air_conditioner",["water_leak"],[],{"تسرب المياه"}),
        ("air_conditioner",["abnormal_noise"],[],{"صوت غير طبيعي"}),
        ("printer",["paper_jam"],[],{"انحشار الورق"}),
        ("printer",["not_working"],[],{"عدم التشغيل"}),
        ("printer",["paper_jam","not_working"],[],{"انحشار الورق","عدم التشغيل"}),
        ("plumbing",["water_leak"],[],{"تسرب المياه"}),
        ("air_conditioner",["water_leak"],["electrical_risk"],{"تعرض المعدات الكهربائية للمياه"}),
        ("air_conditioner",["not_working"],[],set()),
        ("air_conditioner",["low_cooling"],[],set()),
        ("printer",["paper_jam"],["fire_or_smoke"],set()),
        ("heater",["water_leak"],[],set())]
    checks = []
    for device, symptoms, hazards, expected in cases:
        result = retrieve_procedures(device, symptoms, hazards)
        actual = {c.section for c in result}
        if actual != expected:
            raise RuntimeError(f"Semantic acceptance failed: {device}, {symptoms}, {hazards}: {actual} != {expected}")
        check = {"asset_type":device,"symptoms":symptoms,"safety_signals":hazards,"evidence":[c.model_dump() for c in result]}
        checks.append(check)
        print(json.dumps({"device":device,"symptoms":symptoms,"hazards":hazards,"sections":list(actual),"scores":[c.score for c in result]},ensure_ascii=False),flush=True)
    if retrieve_procedures("air_conditioner",["water_leak"],min_score=1):
        raise RuntimeError("Minimum score is not enforced")
    report = {"status":"passed","verified_at":datetime.now(timezone.utc).isoformat(),"count":count,
        "rag_status":get_rag_status(),"checks":checks}
    destination = ROOT / "data" / "reports" / "rag-verification.json"
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"PASSED real local semantic retrieval. Report: {destination}",flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
