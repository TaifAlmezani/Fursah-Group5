# FURSAH backend image. Build from fursah-starter/ (this file's directory):
#   docker build -t fursah-api .
#   docker run -p 8000:8000 --env-file backend/.env fursah-api
#   # keyless/deterministic (no .env needed):
#   docker run -p 8000:8000 fursah-api
#
# The image mirrors the repo layout (backend/ next to data/) because config.py finds the
# project root three folders above itself and reads data/ from there. On Render, PORT is
# injected automatically and the container listens on it.
FROM python:3.12-slim

# Predictable, unbuffered logs; no stray .pyc files.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /srv/fursah/backend

# 1) Dependencies first, so edits to app code don't invalidate the pip layer.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) Application code and the prepared dataset.
COPY backend/app ./app
COPY data /srv/fursah/data

# 3) Build the SQLite store at image-build time (pure local, no API key, no network) so the
#    first request isn't slow. Done as root; the data dir is handed to the app user below.
RUN python -m app.infrastructure.db

# 4) Run as a non-root user. The data dir stays writable because the "مهتم" (interested)
#    table — and SQLite's own -wal/-shm files — are written there at runtime.
RUN useradd --create-home --uid 10001 app \
    && chown -R app:app /srv/fursah/data
USER app

EXPOSE 8000

# Container-level health check (Render also probes /health over HTTP). Uses stdlib so the
# slim image needs no curl.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8000')}/health\").read()" || exit 1

# exec form keeps uvicorn as PID 1 (clean shutdown signals); ${PORT} is set by Render.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
