"""Acceptance through this checkout's API, real local ASL and real FAISS.

Only embedding weights are borrowed read-only; index, tickets and checkpoints
are temporary. The already-running model service is never started or stopped.
"""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qa_neural_extraction import ExistingLocalModel
from app.config import settings
from app.db.database import get_ticket
from app.llm import client as llm
from app.rag import engine as rag
from app.workflow import graph
from app.policies.rules import SAFETY_MESSAGES


class BorrowedModel(ExistingLocalModel):
    def __init__(self):
        super().__init__()
        self._loaded = self._generation_verified = True
        self._device = "cpu"

    def initialize(self):
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedding-model-path", required=True)
    args = parser.parse_args()
    with httpx.Client(trust_env=False, timeout=5) as api:
        ready = api.get("http://127.0.0.1:8000/ready").json()
    assert ready["model_status"]["is_neural_loaded"] and ready["model_status"]["engine"] == "llama_cpp"
    report = ROOT / "data/reports/qa-neural-workflow.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    checks = []
    with TemporaryDirectory(prefix="saai-qa-neural-") as directory:
        settings.db_path = str(Path(directory) / "app.db")
        settings.checkpoints_db_path = str(Path(directory) / "checkpoints.db")
        settings.vectorstore_path = str(Path(directory) / "rag")
        settings.embedding_model_path = str(Path(args.embedding_model_path).resolve())
        settings.llm_mode = "neural"
        settings.llm_engine = "llama_cpp"
        llm._client_instance = BorrowedModel()
        rag.build_rag_index()
        print("Temporary real-embedding index built", flush=True)
        from app.main import app
        from fastapi.testclient import TestClient

        def run(name, function):
            observation = {"case": name, "requests": []}
            started = time.perf_counter()
            try:
                function(observation)
                observation["passed"] = True
            except Exception as exc:
                observation.update(passed=False, error_type=type(exc).__name__, error=str(exc))
            observation["duration_seconds"] = round(time.perf_counter() - started, 2)
            checks.append(observation)
            report.write_text(json.dumps({"mode": "real local ASL + real embeddings + current API + temporary SQLite/index",
                                         "rag_min_score": settings.rag_min_score, "cases": checks}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: v for k, v in observation.items() if k != "requests"}, ensure_ascii=False), flush=True)

        with TestClient(app) as api:
            def post(observation, url, payload):
                response = api.post(url, json=payload)
                body = response.json()
                observation["requests"].append({"payload": payload, "http": response.status_code, "body": body})
                assert response.status_code == 200, body
                if "ticket" in body:
                    ticket = get_ticket(body["ticket"]["ticket_id"], settings.db_path)
                    assert ticket["thread_id"] == body["thread_id"]
                    assert ticket["asset_id"] == body["asset"]["asset_id"]
                    assert ticket["status"] == body["ticket"]["status"]
                    assert ticket["recommended_action"] == body["recommended_action"]
                    assert ticket["safety_message"] == body.get("safety_message")
                return body

            def basic(observation):
                body = post(observation, "/api/maintenance/requests", {"description": "المكيف يهرب موية", "location": "B12"})
                assert body["status"] == "success" and body["asset"]["asset_id"] == "AC-B12-02"
                assert body["recommendation_status"] == "grounded"
                assert [item["section"] for item in body["evidence"]] == ["تسرب المياه"]

            def combined(observation):
                body = post(observation, "/api/maintenance/requests", {"description": "المكيف يهرب موية على اللوحة الكهربائية وفيه دخان", "location": "B12"})
                assert body["status"] == "critical" and body["ticket"]["status"] == "escalated"
                assert set(body["analysis"]["safety_signals"]) == {"fire_or_smoke", "electrical_risk"}
                assert body["safety_message"] == " ".join(SAFETY_MESSAGES[s] for s in ["fire_or_smoke", "electrical_risk"])
                assert all(item["source"] == "electrical.md" for item in body["evidence"])

            def negated(observation):
                body = post(observation, "/api/maintenance/requests", {"description": "المكيف ما يبرد، ما فيه دخان ولا ريحة حريق ولا تسريب", "location": "B12"})
                assert body["status"] == "success" and not body.get("safety_message")
                assert body["analysis"]["safety_signals"] == []

            def clarification(observation):
                first = post(observation, "/api/maintenance/requests", {"description": "الطابعة تعلق الورق"})
                assert first["status"] == "needs_information"
                url = f"/api/maintenance/requests/{first['thread_id']}/continue"
                choice = post(observation, url, {"input_type": "text", "text": "الدور الثالث", "step_id": first["step_id"]})
                assert choice["status"] == "needs_asset_selection" and len(choice["assets"]) == 3
                last = post(observation, url, {"input_type": "asset_selection", "asset_id": "PR-305-01", "step_id": choice["step_id"]})
                assert last["status"] == "success" and last["asset"]["asset_id"] == "PR-305-01"

            def numerals(observation):
                body = post(observation, "/api/maintenance/requests", {"description": "الطابعة تعلق الورق في غرفة ٣٠١"})
                assert body["status"] == "success" and body["asset"]["asset_id"] == "PR-301-01"

            try:
                for name, function in [("grounded_leak", basic), ("combined_hazards", combined),
                                       ("negated_hazards", negated), ("clarification_and_choice", clarification),
                                       ("arabic_numerals", numerals)]:
                    run(name, function)
            finally:
                if graph.workflow_graph is not None:
                    graph.workflow_graph.checkpointer.conn.close()
                    graph.workflow_graph = None
    return 0 if all(check["passed"] for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
