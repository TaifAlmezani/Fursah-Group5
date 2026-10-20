import pytest
from app.config import settings
from app.llm import client as llm
from app.workflow import graph
from app.db.database import init_db
from app.rag import engine as rag


class ControlledEmbedder:
    """Predictable vectors for retrieval mechanics tests; real embeddings have a separate acceptance run."""
    def encode(self, texts, **kwargs):
        import numpy as np
        rows = []
        terms = [("تسرب", "المياه"), ("صوت", "اهتزاز"), ("انحشار", "الورق"),
            ("عدم التشغيل", "الطاقة"), ("خطر كهربائي", "تعرض"), ("المكيف", "التكييف"), ("الطابعة", "الطابعات")]
        for text in texts:
            row = np.zeros(16, dtype="float32")
            row[0] = 0.25
            for i, words in enumerate(terms, 1):
                row[i] = float(any(word in text for word in words))
            rows.append(row)
        return np.asarray(rows)


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "app.db"))
    monkeypatch.setattr(settings, "checkpoints_db_path", str(tmp_path / "checkpoints.db"))
    monkeypatch.setattr(graph, "workflow_graph", None)
    monkeypatch.setattr(settings, "llm_mode", "heuristic")
    monkeypatch.setattr(settings, "vectorstore_path", str(tmp_path / "rag"))
    monkeypatch.setattr(rag, "_encoder", ControlledEmbedder())
    monkeypatch.setattr(rag, "_encoder_key", ("test",))
    monkeypatch.setattr(rag, "_model_key", lambda:("test",))
    monkeypatch.setattr(rag, "_indexes", {})
    rag.build_rag_index()
    client = llm.LocalASLClient()
    client._load_attempted = True
    monkeypatch.setattr(llm, "_client_instance", client)
    init_db(settings.db_path, settings.seed_path)
    yield
    if graph.workflow_graph is not None:
        graph.workflow_graph.checkpointer.conn.close()
