"""Download official ASL once and verify actual local neural inference."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", default=settings.llm_model_path)
    parser.add_argument("--serve", action="store_true", help="After verification, serve the backend using the already-loaded model")
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--download-only", action="store_true")
    options.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    settings.llm_model_path = str(Path(args.model_dir).resolve())
    settings.llm_mode = "neural"
    if not args.verify_only:
        from huggingface_hub import snapshot_download
        print(f"Downloading {settings.llm_model}@{settings.llm_revision} to {settings.llm_model_path}", flush=True)
        snapshot_download(repo_id=settings.llm_model, revision=settings.llm_revision,
            local_dir=settings.llm_model_path, max_workers=2,
            allow_patterns=["*.json", "*.jinja", "*.txt", "*.safetensors", "LICENSE", "README.md"])
    if args.download_only:
        print("Download complete; generation is not verified yet.", flush=True)
        return 0
    from app.llm.client import get_llm_client
    from app.llm.agents import extract_issue, compose_recommendation
    client = get_llm_client()
    print("Loading local ASL and testing generation...", flush=True)
    if not client.initialize():
        print("FAILED: local neural loading/generation. See preceding error.", file=sys.stderr)
        return 1
    checks = []
    print("Initial generation succeeded. Testing structured extraction...", flush=True)
    for description, location, device, expected_symptoms, signal in [
            ("المكيف لا يعمل", "B12", "air_conditioner", {"not_working"}, None),
            ("المكيف يهرب موية على اللوحة الكهربائية", None, "air_conditioner", {"water_leak"}, "electrical_risk"),
            ("الطابعة تعلق الورق وما تطبع", "الدور الثالث", "printer", {"paper_jam", "not_working"}, None),
            ("السلام عليكم", None, None, set(), None)]:
        start = time.perf_counter()
        issue = extract_issue(description, location)
        if issue.asset_type != device or not expected_symptoms.issubset(issue.symptoms):
            raise RuntimeError("Device/symptom extraction acceptance check failed")
        if device is None and (issue.symptoms or "asset_type" not in issue.missing_fields or "symptoms" not in issue.missing_fields):
            raise RuntimeError("Unreported facts must not be invented")
        if signal and signal not in issue.safety_signals:
            raise RuntimeError("Electrical risk acceptance check failed")
        if location is None and (issue.location is not None or "location" not in issue.missing_fields):
            raise RuntimeError("Missing location acceptance check failed")
        checks.append({"description":description, "result":issue.model_dump(), "duration_ms":round((time.perf_counter()-start)*1000,2)})
        print(json.dumps(checks[-1], ensure_ascii=False), flush=True)
    rec = compose_recommendation([{"source":"air_conditioning.md", "content":"فحص مجرى تصريف مياه التكثف للتأكد من عدم وجود انسداد.", "score":1.0}], {"asset_type":"air_conditioner", "symptoms":["water_leak"]})
    if not rec.recommended_action.strip():
        raise RuntimeError("Empty recommendation")
    report = {"status":"passed", "verified_at":datetime.now(timezone.utc).isoformat(), "model_status":client.get_status(), "checks":checks, "recommendation":rec.model_dump()}
    output = ROOT / "data" / "reports" / "llm-verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"PASSED real local ASL generation, extraction, hazard detection, recommendation. Report: {output}",flush=True)
    if args.serve:
        import uvicorn
        uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
