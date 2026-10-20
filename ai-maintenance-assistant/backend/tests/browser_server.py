"""Isolated browser regression server. Explicit heuristic + controlled test vectors.

Never imported by app.main; test-only inspection routes never reach production.
Real neural/embedding acceptance is a separate setup/verification run.
"""
import atexit
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings
from app.rag import engine as rag
from conftest import ControlledEmbedder

runtime = TemporaryDirectory(prefix='saai-browser-tests-')
settings.db_path = str(Path(runtime.name) / 'app.db')
settings.checkpoints_db_path = str(Path(runtime.name) / 'checkpoints.db')
settings.vectorstore_path = str(Path(runtime.name) / 'rag')
settings.llm_mode = 'heuristic'
rag._encoder = ControlledEmbedder()
rag._encoder_key = ('test',)
rag._model_key = lambda: ('test',)
rag.build_rag_index()

from app.main import app
from app.workflow import nodes, graph
from app.db.database import get_db_connection

original_extract = nodes.extract_issue
def browser_extract(description, **kwargs):
    # Keep pending UI deterministic and inject a separately labelled failure.
    time.sleep(0.2)
    if description == 'اختبار فشل الاستخراج':
        raise RuntimeError('TEST_PRIVATE_BACKEND_ERROR')
    if description == 'اختبار سياسة المخاطر المتعددة':
        # Explicit model-output fixture for the browser policy test; the real
        # workflow, safety rules and SQLite persistence still execute normally.
        issue = original_extract('المكيف يهرب موية على اللوحة الكهربائية', **kwargs)
        issue.safety_signals = (['electrical_risk', 'fire_or_smoke', 'electrical_risk']
                                if kwargs.get('follow_up_answers') else ['electrical_risk'])
        return issue
    return original_extract(description, **kwargs)
nodes.extract_issue = browser_extract

@app.get('/__test__/tickets/{thread_id}')
def saved_ticket(thread_id: str):
    with get_db_connection(settings.db_path) as connection:
        row = connection.execute('SELECT * FROM tickets WHERE thread_id=?', (thread_id,)).fetchone()
        return dict(row) if row else None

@app.get('/__test__/mode')
def test_mode():
    return {'llm':'explicit_heuristic', 'embeddings':'controlled_test_vectors', 'database':'temporary'}

def cleanup():
    if graph.workflow_graph is not None:
        graph.workflow_graph.checkpointer.conn.close()
    runtime.cleanup()
atexit.register(cleanup)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8018, log_level='warning')
