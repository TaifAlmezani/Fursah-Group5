import json
import logging
import re
import sys
import time
from pathlib import Path
from threading import RLock
from typing import Any, TypeVar
from pydantic import BaseModel, ValidationError
from app.config import settings

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)
_client_instance = None


class ModelUnavailableError(RuntimeError):
    """Neural inference is unavailable; never substitute heuristic output."""


class StructuredOutputError(RuntimeError):
    """Model output failed the application's JSON/schema contract."""


def _positive_mention(text: str, phrases: list[str]) -> bool:
    """Limited demo parsing: exclude explicitly negated nearby mentions."""
    for phrase in phrases:
        for match in re.finditer(re.escape(phrase), text):
            prefix = re.split(r"[،,.;؛!?؟\n]|\b(?:لكن|ولكن|بس)\b", text[:match.start()])[-1]
            negated = re.search(
                r"(?:ما\s*(?:فيه|في)|لا\s*(?:يوجد|توجد)|بدون|ليس\s+هناك|ولا|\bلا)\s*"
                r"(?:(?:أي|اي|أثر|اثر|علامات|ريحة|رائحة)\s+){0,3}$", prefix)
            if not negated:
                return True
    return False


def parse_structured_output(raw: str, output_schema: type[T]) -> T:
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
        return output_schema.model_validate(data)
    except (ValueError, ValidationError, TypeError) as exc:
        raise StructuredOutputError("The model did not return valid structured output") from exc


class LocalASLClient:
    """Local-only ASL inference. Downloads are an explicit setup operation."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.llm_model
        self.tokenizer = None
        self.model = None
        self._loaded = False
        self._load_attempted = False
        self._generation_verified = False
        self._last_error = None
        self._last_duration_ms = None
        self._device = None
        self._lock = RLock()

    def load_model(self, force_download: bool = False) -> bool:
        with self._lock:
            if self._loaded:
                return True
            self._load_attempted = True
            try:
                runtime_path = Path(settings.llm_runtime_path)
                if runtime_path.is_dir() and str(runtime_path) not in sys.path:
                    sys.path.insert(0, str(runtime_path))
                if force_download:
                    from huggingface_hub import snapshot_download
                    snapshot_download(repo_id=self.model_name, revision=settings.llm_revision,
                                      local_dir=settings.llm_model_path, max_workers=2)
                model_path = Path(settings.llm_model_path)
                if not (model_path / "config.json").is_file():
                    raise FileNotFoundError("Run python scripts/setup_llm.py before starting the backend")
                import torch
                from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig
                device = settings.llm_device
                if device == "auto":
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                if device == "cuda" and not torch.cuda.is_available():
                    raise RuntimeError("CUDA was requested but is not available")
                if device == "cpu":
                    torch.set_num_threads(settings.llm_cpu_threads)
                if device == "cpu":
                    supports_bf16 = getattr(torch.cpu, "_is_avx512_bf16_supported", lambda: False)()
                    dtype = torch.bfloat16 if supports_bf16 else torch.float32
                else:
                    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
                kwargs = {"local_files_only": True, "trust_remote_code": False,
                          "dtype": dtype, "device_map": {"": device}, "attn_implementation": "sdpa"}
                if settings.llm_quantization == "4bit":
                    kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True, bnb_4bit_quant_type="nf4",
                        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype)
                logger.info("Loading %s locally on %s (%s)", self.model_name, device, settings.llm_quantization)
                tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=False)
                model = AutoModelForImageTextToText.from_pretrained(str(model_path), **kwargs)
                model.eval()
                self.tokenizer, self.model = tokenizer, model
                self._device, self._loaded, self._last_error = device, True, None
                return True
            except Exception:
                self.model, self.tokenizer = None, None
                self._loaded = self._generation_verified = False
                self._last_error = "model_load_failed"
                logger.exception("Local ASL loading failed")
                return False

    def get_status(self) -> dict[str, Any]:
        return {
            "model": self.model_name, "revision": settings.llm_revision,
            "configured_mode": settings.llm_mode,
            "mode": "fast_heuristic_mode" if settings.llm_mode == "heuristic" else "neural_asl_4b_v1" if self._loaded else "neural_not_loaded",
            "is_neural_loaded": self._loaded, "generation_verified": self._generation_verified,
            "device": self._device, "quantization": settings.llm_quantization,
            "last_generation_ms": self._last_duration_ms, "error": self._last_error,
        }

    def generate(self, system_prompt: str, user_payload: dict[str, Any], max_new_tokens: int | None = None, json_schema: dict | None = None) -> str:
        if settings.llm_mode == "heuristic":
            return self._heuristic_fallback(user_payload)
        with self._lock:
            if not self._loaded and not self.load_model():
                raise ModelUnavailableError("Local ASL is not ready. Run scripts/setup_llm.py")
            import torch
            messages = [{"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}]
            prompt = self.tokenizer.apply_chat_template(messages, tokenize=False,
                                                       add_generation_prompt=True, enable_thinking=False)
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self._device)
            if inputs["input_ids"].shape[-1] > 4096:
                raise StructuredOutputError("Input exceeds the local inference context limit")
            started = time.perf_counter()
            try:
                with torch.inference_mode():
                    output = self.model.generate(**inputs,
                        max_new_tokens=max_new_tokens or settings.llm_max_new_tokens,
                        do_sample=False, max_time=settings.llm_timeout_seconds,
                        pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id)
                text = self.tokenizer.decode(output[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True).strip()
                if not text:
                    raise StructuredOutputError("The model returned empty output")
                self._generation_verified = True
                self._last_error = None
                return text
            except Exception:
                self._generation_verified = False
                self._last_error = "model_generation_failed"
                logger.exception("Local ASL generation failed")
                raise
            finally:
                self._last_duration_ms = round((time.perf_counter() - started) * 1000, 2)

    def initialize(self) -> bool:
        if settings.llm_mode == "heuristic":
            return True
        if not self.load_model():
            return False
        try:
            self.generate('Return exactly the JSON object {"ready":true}, without explanation.',
                          {"instruction": "Confirm you can generate text."}, max_new_tokens=32)
            return self._generation_verified
        except Exception:
            return False

    def _heuristic_fallback(self, payload: dict[str, Any]) -> str:
        """Lightweight parsing engine for local demos without downloading 8GB weights."""
        desc = payload.get("description", "").lower()
        loc = payload.get("location") or ""
        answers = payload.get("follow_up_answers", [])
        
        # Merge all user text from description and clarification answers
        full_text = desc
        for a in answers:
            ans_text = a.get("answer", "")
            full_text += f" {ans_text.lower()}"

        # 1. Determine asset type
        asset_type = None
        if any(w in full_text for w in ["مكيف", "تبريد", "ac", "air"]):
            asset_type = "air_conditioner"
        elif any(w in full_text for w in ["طابعة", "ورق", "حبر", "printer"]):
            asset_type = "printer"
        elif any(w in full_text for w in ["تسريب", "سباكة", "ماسورة", "مغسلة", "مياه", "بلوعة"]):
            asset_type = "plumbing"
        elif any(w in full_text for w in ["كهرباء", "التماس", "فيش", "قاطع", "أسلاك"]):
            asset_type = "electrical"

        if asset_type is None and any(w in full_text for w in ["سخان", "دفاية", "heater"]):
            asset_type = "heater"

        # 2. Determine location
        extracted_loc = loc
        if not extracted_loc:
            # Search in description first, then answers
            room_match = re.search(r"(مكتب|غرفة|معمل|دور|مبنى|طابق|b\d+|\d+)\s*(\d+|[أ-يa-zA-Z]+)?", full_text)
            if room_match:
                extracted_loc = room_match.group(0).strip()
            for a in answers:
                if a.get("answer"):
                    extracted_loc = a["answer"].strip()
                    break

        # 3. Symptoms
        symptoms = []
        water = _positive_mention(full_text, ["موية", "تنقيط", "تسريب", "تهريب", "تسرب", "يسرب ماء", "ينقط"])
        if water:
            symptoms.append("water_leak")
        if _positive_mention(full_text, ["صوت", "ازعاج", "ضجيج"]):
            symptoms.append("abnormal_noise")
        if _positive_mention(full_text, ["ما يشتغل", "ما تشتغل", "طافي", "عطلان", "لا يعمل", "لا تعمل", "خربان", "ما تطبع"]):
            symptoms.append("not_working")
        if _positive_mention(full_text, ["حشر", "ورق", "عالق"]):
            symptoms.append("paper_jam")
        if _positive_mention(full_text, ["حار", "ما يبرد", "ضعف التبريد"]):
            symptoms.append("low_cooling")

        # 4. Safety signals
        safety_signals = []
        if water and _positive_mention(full_text, ["كهرب", "التماس", "فيش"]):
            safety_signals.append("electrical_risk")
        if _positive_mention(full_text, ["دخان", "ريحة حريق", "حريق", "شرار"]):
            safety_signals.append("fire_or_smoke")
        if _positive_mention(full_text, ["أسلاك مكشوفة", "اسلاك مكشوفة"]):
            safety_signals.append("exposed_wires")
        if _positive_mention(full_text, ["فيضان", "تسريب كثيف", "تسرب كثيف"]):
            safety_signals.append("flooding")

        missing = []
        if not asset_type:
            missing.append("asset_type")
        if not extracted_loc:
            missing.append("location")
        if not symptoms:
            missing.append("symptoms")

        # Recommendation response
        if "procedures" in payload or "issue_context" in payload:
            procedures = payload.get("procedures", [])
            if payload.get("selection_task"):
                return json.dumps({"procedure_ids":[p["procedure_id"] for p in procedures]}, ensure_ascii=False)
            if procedures:
                content = procedures[0].get("content", "")
                summary = content.split("\n")[0].replace("#", "").strip()
                action = f"فحص الجهاز وتطبيق الإجراء المعتمد: {summary}"
            else:
                action = "سيتم تحويل البلاغ لفريق الصيانة للمراجعة والفحص الميداني."
            return json.dumps({"recommended_action": action}, ensure_ascii=False)

        return json.dumps({
            "asset_type": asset_type,
            "location": extracted_loc or None,
            "symptoms": symptoms,
            "safety_signals": safety_signals,
            "missing_fields": missing
        }, ensure_ascii=False)



def get_llm_client() -> LocalASLClient:
    global _client_instance
    if _client_instance is None:
        if settings.llm_engine == "llama_cpp" and settings.llm_mode == "neural":
            from .llama_cpp import LlamaCppASLClient
            _client_instance = LlamaCppASLClient()
        else:
            _client_instance = LocalASLClient()
    return _client_instance


def run_structured_model(output_schema: type[T], system_prompt: str, user_payload: dict[str, Any]) -> T:
    client = get_llm_client()
    # llama.cpp enforces the schema through its grammar; avoid duplicate schema tokens on CPU.
    schema_prompt = system_prompt if settings.llm_engine == "llama_cpp" else system_prompt + "\nJSON schema: " + json.dumps(output_schema.model_json_schema(), ensure_ascii=False)
    raw_response = client.generate(schema_prompt, user_payload, json_schema=output_schema.model_json_schema())
    return parse_structured_output(raw_response, output_schema)
