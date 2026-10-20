"""Seed-based acceptance: real running local ASL, real embeddings, isolated data.

The malformed JSON and empty formatter checks are deliberately controlled and
reported separately. Requires a neural llama.cpp backend already running.
"""
import sys,json,time,tempfile,sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from datetime import datetime,timezone
import httpx
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings
from app.llm import client as llm
from app.llm.client import LocalASLClient,ModelUnavailableError,StructuredOutputError
from app.workflow import graph

live = ROOT
import argparse
parser = argparse.ArgumentParser(description='Real local llama.cpp ASL + RAG acceptance with an isolated SQLite database.')
parser.add_argument('--base-url', default='http://127.0.0.1:8000')
args = parser.parse_args()
assert settings.llm_engine == 'llama_cpp', 'This acceptance driver requires the local llama.cpp engine.'
asl_url = f'http://127.0.0.1:{settings.llm_server_port}/v1/chat/completions'
report_path = live / 'data/reports/local-stack-verification.json'
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps({'status':'running', 'verified_at':datetime.now(timezone.utc).isoformat()}), encoding='utf-8')
with httpx.Client(trust_env=False,timeout=5) as api:
    ready=api.get(args.base_url.rstrip('/') + '/ready').json()
assert ready['model_status']['is_neural_loaded'] and ready['model_status']['mode']=='neural_asl_4b_v1'
class ExistingLocalASL(LocalASLClient):
    def __init__(self):
        super().__init__(); self._loaded=True; self._device='cpu'
    def load_model(self): return True
    def generate(self,system_prompt,user_payload,max_new_tokens=None,json_schema=None):
        start=time.perf_counter()
        with httpx.Client(trust_env=False,timeout=240) as api:
            response=api.post(asl_url,json={'model':settings.llm_model,'messages':[{'role':'system','content':system_prompt},{'role':'user','content':json.dumps(user_payload,ensure_ascii=False)}],'temperature':0,'max_tokens':max_new_tokens or 256,'chat_template_kwargs':{'enable_thinking':False},'response_format':{'type':'json_object',**({'schema':json_schema} if json_schema else {})}})
            response.raise_for_status()
        choice=response.json()['choices'][0]
        if choice.get('finish_reason')=='length': raise StructuredOutputError('truncated output')
        self._generation_verified=True; self._last_duration_ms=round((time.perf_counter()-start)*1000,2)
        return choice['message']['content']

@contextmanager
def isolated_directory():
    with tempfile.TemporaryDirectory(prefix='saai-local-stack-') as temp:
        try:
            yield temp
        finally:
            if graph.workflow_graph is not None:
                graph.workflow_graph.checkpointer.conn.close()
                graph.workflow_graph = None

checks=[]
with isolated_directory() as temp:
    settings.db_path=str(Path(temp)/'app.db'); settings.checkpoints_db_path=str(Path(temp)/'checkpoints.db')
    # Keep configured local knowledge and vectorstore paths; isolate only the databases.
    # Use the embedding model path already configured in .env.
    settings.llm_mode='neural'; settings.llm_engine='llama_cpp'
    llm._client_instance=ExistingLocalASL()
    from app.main import app
    from fastapi.testclient import TestClient
    from app.rag.engine import get_rag_status
    def post(api,url,payload):
        start=time.perf_counter(); result=api.post(url,json=payload)
        data=result.json(); check={'payload':payload,'http_status':result.status_code,'result':data,'duration_ms':round((time.perf_counter()-start)*1000,2)}
        checks.append(check); print(json.dumps({'status':data.get('status'),'http_status':result.status_code,'duration_ms':check['duration_ms'],'description':payload.get('description'),'input_type':payload.get('input_type')},ensure_ascii=False),flush=True)
        assert result.status_code==200,data
        assert all(isinstance(t['duration_ms'],(float,int)) and t['duration_ms'] >= 0 for t in data.get('trace',[])),data
        assert not data.get('trace') or not all(t['duration_ms']==15 for t in data['trace'])
        if data.get('ticket'):
            with closing(sqlite3.connect(settings.db_path)) as c:
                row=c.execute('SELECT asset_id,status,recommended_action,recommendation_status,recommendation_evidence,thread_id FROM tickets WHERE ticket_id=?',(data['ticket']['ticket_id'],)).fetchone()
            assert row and row[0]==data['asset']['asset_id'] and row[5]==data['thread_id'] and row[1]==data['ticket']['status'] and row[2]==data['recommended_action'] and row[3]==data['recommendation_status']
            evidence=json.loads(row[4]); assert {e['procedure_id'] for e in evidence}=={e['procedure_id'] for e in data['evidence']}
            if evidence:
                expected='\n\n'.join(e['content'].removeprefix('## ').strip() for e in evidence)
                assert data['recommended_action'].startswith(expected)
            print('ISOLATED_DB_VERIFIED',data['ticket']['ticket_id'],flush=True)
        report_path.write_text(json.dumps({'status':'running','mode':'real local ASL + real FAISS embeddings + isolated API/database','checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
        return data
    with TestClient(app) as api:
        assert api.get('/ready').status_code==200
        leak=post(api,'/api/maintenance/requests',{'description':'المكيف يهرب موية','location':'B12'})
        assert leak['status']=='success' and leak['recommendation_status']=='grounded' and [e['section'] for e in leak['evidence']]==['تسرب المياه']
        printer=post(api,'/api/maintenance/requests',{'description':'الطابعة تعلق الورق وما تطبع','location':'الدور الثالث'})
        assert printer['status']=='needs_asset_selection'
        assert len(printer['assets'])==3
        bad=api.post('/api/maintenance/requests/'+printer['thread_id']+'/continue',json={'step_id':printer['step_id'],'input_type':'asset_selection','asset_id':'DOES-NOT-EXIST'})
        assert bad.status_code==422
        selected=post(api,'/api/maintenance/requests/'+printer['thread_id']+'/continue',{'step_id':printer['step_id'],'input_type':'asset_selection','asset_id':'PR-305-01'})
        assert selected['status']=='success' and {e['section'] for e in selected['evidence']}=={'انحشار الورق','عدم التشغيل'}
        assert selected['asset']['asset_id']=='PR-305-01'
        assert api.post('/api/maintenance/requests/'+printer['thread_id']+'/continue',json={'step_id':printer['step_id'],'input_type':'asset_selection','asset_id':'PR-305-01'}).status_code==409
        hazard=post(api,'/api/maintenance/requests',{'description':'المكيف يهرب موية على اللوحة الكهربائية','location':'B12'})
        assert hazard['status']=='critical' and [e['source'] for e in hazard['evidence']]==['electrical.md']
        assert 'صينية' not in hazard['recommended_action'] and 'مجرى' not in hazard['recommended_action']
        missing=post(api,'/api/maintenance/requests',{'description':'المكيف لا يعمل','location':'B12'})
        assert missing['status']=='success' and missing['recommendation_status']=='manual_review' and missing['evidence']==[]
        partial=post(api,'/api/maintenance/requests',{'description':'المكيف يهرب موية وما يشتغل','location':'B12'})
        assert partial['recommendation_status']=='partial' and [e['source'] for e in partial['evidence']]==['air_conditioning.md']
        unknown=post(api,'/api/maintenance/requests',{'description':'المكيف لا يعمل','location':'غرفة 999'})
        assert unknown['status']=='asset_not_found' and 'ticket' not in unknown
        office=post(api,'/api/maintenance/requests',{'description':'المكيف لا يعمل'})
        assert office['status']=='needs_information'
        office_end=post(api,'/api/maintenance/requests/'+office['thread_id']+'/continue',{'step_id':office['step_id'],'input_type':'text','text':'مكتب 204'})
        assert office_end['status']=='asset_not_found'
        unregistered=post(api,'/api/maintenance/requests',{'description':'السخان ما يشتغل','location':'المستودع 7'})
        assert unregistered['status']=='asset_not_found'
        paused=post(api,'/api/maintenance/requests',{'description':'المكيف يهرب موية على اللوحة الكهربائية'})
        assert paused['status']=='needs_information' and paused['safety_message']
        finished=post(api,'/api/maintenance/requests/'+paused['thread_id']+'/continue',{'step_id':paused['step_id'],'input_type':'text','text':'B12'})
        assert finished['status']=='critical' and finished['trace'][:len(paused['trace'])]==paused['trace']
        with closing(sqlite3.connect(settings.db_path)) as c:
            c.execute("UPDATE assets SET status='inactive' WHERE asset_id='PR-310-01'"); c.commit()
        unavailable=post(api,'/api/maintenance/requests',{'description':'الطابعة تعلق الورق','location':'310'})
        assert unavailable['status']=='asset_not_found' and 'خارج الخدمة' in unavailable['message']
        assert leak['asset']['model']=='Demo-AC-01'
        from app.main import _format_frontend_response
        assert _format_frontend_response({},'REQ-empty','th-empty')['status']=='error'
        from app.rag.engine import retrieve_procedures
        assert retrieve_procedures('air_conditioner',['water_leak'],['electrical_risk'],min_score=.99)==[]
        # Deliberate malformed-output injection is separate from the genuine neural cases above.
        bridge=llm._client_instance; original_generate=bridge.generate
        bridge.generate=lambda *args,**kwargs:'NOT VALID JSON'
        malformed=api.post('/api/maintenance/requests',json={'description':'المكيف لا يعمل','location':'B12'})
        bridge.generate=original_generate
        assert malformed.status_code==502 and malformed.json()['error_code']=='invalid_model_output'
        assert 'NOT NULL' not in malformed.json()['message'] and 'ticket' not in malformed.json()
        with closing(sqlite3.connect(settings.db_path)) as c:
            assert c.execute('SELECT COUNT(*) FROM tickets WHERE thread_id=?',(malformed.json()['thread_id'],)).fetchone()[0]==0
        print('CONTROLLED_MALFORMED_OUTPUT_REJECTED_502',flush=True)
        rag_status=get_rag_status()
        original=settings.vectorstore_path; settings.vectorstore_path=str(Path(temp)/'missing-index')
        assert api.get('/ready').status_code==503
        settings.vectorstore_path=original
report={'status':'passed','verified_at':datetime.now(timezone.utc).isoformat(),'mode':'real local ASL + real FAISS embeddings + isolated API/database','user_database_modified':False,'rag_status':rag_status,'checks':checks,'separate_controlled_checks':['malformed_output_502_no_ticket','empty_formatter_no_success'],'real_retrieval_threshold_check':True}
(live/'data/reports/local-stack-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('LOCAL_ASL_API_DB_PASSED',flush=True)
