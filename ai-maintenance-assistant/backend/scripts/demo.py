"""Submit a demo through the running backend; creates one real maintenance ticket."""
import argparse
import json
from pathlib import Path
import sys
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings


def run_demo():
    parser = argparse.ArgumentParser(description="بلاغ تجريبي عبر backend الشغّال؛ ينشئ تذكرة فعلية.")
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--description', default='المكيف يهرب موية على اللوحة الكهربائية')
    parser.add_argument('--location', default='B12')
    args = parser.parse_args()
    with httpx.Client(trust_env=False, timeout=settings.llm_timeout_seconds * 2) as api:
        response = api.post(args.base_url.rstrip('/') + '/api/maintenance/requests',
                            json={'description': args.description, 'location': args.location})
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    return 0 if response.is_success else 1


if __name__ == '__main__':
    raise SystemExit(run_demo())
