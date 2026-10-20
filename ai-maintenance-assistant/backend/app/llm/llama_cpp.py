"""Local CPU inference using an owned llama.cpp process and converted ASL weights."""
import atexit
import hashlib
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import time

import httpx
from app.config import settings
from .client import LocalASLClient, ModelUnavailableError, StructuredOutputError

logger = logging.getLogger(__name__)


class LlamaCppASLClient(LocalASLClient):
    def __init__(self):
        super().__init__()
        self._process = None
        self._runtime_log = None
        atexit.register(self.shutdown)

    def shutdown(self):
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
        if self._runtime_log is not None:
            self._runtime_log.close()
            self._runtime_log = None
        self._loaded = self._generation_verified = False

    @property
    def _url(self):
        return f"http://127.0.0.1:{settings.llm_server_port}"

    def load_model(self, force_download=False):
        with self._lock:
            if self._loaded and self._process is not None and self._process.poll() is None:
                return True
            self.shutdown()
            self._load_attempted = True
            try:
                executable = Path(settings.llm_server_executable)
                weights = Path(settings.llm_gguf_path)
                if not executable.is_file() or not weights.is_file():
                    raise FileNotFoundError("Configure local llama.cpp executable and ASL GGUF weights")
                provenance = json.loads(weights.with_suffix(".provenance.json").read_text(encoding="utf-8"))
                if provenance.get("model") != self.model_name or provenance.get("revision") != settings.llm_revision or provenance.get("quantization") != "Q4_K_M":
                    raise RuntimeError("GGUF provenance does not match the configured official ASL revision")
                with weights.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != provenance.get("gguf_sha256"):
                        raise RuntimeError("ASL GGUF integrity check failed")
                # Refuse to connect to an unrelated service already using this port.
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", settings.llm_server_port)) == 0:
                        raise RuntimeError("The configured local model port is already occupied")
                log_path = Path(settings.base_dir) / "data" / "logs" / "llama-runtime.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                self._runtime_log = log_path.open("a", encoding="utf-8")
                arguments = [str(executable), "-m", str(weights), "--host", "127.0.0.1",
                    "--port", str(settings.llm_server_port), "--alias", self.model_name,
                    "-c", "4096", "-t", str(settings.llm_cpu_threads), "-np", "1",
                    "-ngl", "0", "--jinja", "--reasoning", "off"]
                self._process = subprocess.Popen(arguments, cwd=executable.parent,
                    stdout=self._runtime_log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                deadline = time.monotonic() + 120
                with httpx.Client(trust_env=False, timeout=2) as api:
                    while time.monotonic() < deadline:
                        if self._process.poll() is not None:
                            raise RuntimeError("Local model process exited; see data/logs/llama-runtime.log")
                        try:
                            if api.get(self._url + "/health").status_code == 200:
                                self._loaded, self._device, self._last_error = True, "cpu", None
                                return True
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.5)
                raise TimeoutError("Local model startup exceeded 120 seconds")
            except Exception:
                logger.exception("Local llama.cpp ASL loading failed")
                self.shutdown()
                self._last_error = "model_load_failed"
                return False

    def get_status(self):
        if self._process is not None and self._process.poll() is not None:
            self._loaded = self._generation_verified = False
            self._last_error = "model_process_exited"
        return {**super().get_status(), "engine": "llama_cpp", "quantization": "Q4_K_M"}

    def generate(self, system_prompt, user_payload, max_new_tokens=None, json_schema=None):
        if settings.llm_mode == "heuristic":
            return self._heuristic_fallback(user_payload)
        with self._lock:
            if not self.load_model():
                raise ModelUnavailableError("The local ASL process is not ready")
            started = time.perf_counter()
            try:
                with httpx.Client(trust_env=False, timeout=settings.llm_timeout_seconds) as api:
                    response = api.post(self._url + "/v1/chat/completions", json={
                        "model": self.model_name,
                        "messages": [{"role":"system", "content":system_prompt},
                            {"role":"user", "content":json.dumps(user_payload, ensure_ascii=False)}],
                        "temperature":0, "max_tokens":max_new_tokens or settings.llm_max_new_tokens,
                        "chat_template_kwargs":{"enable_thinking":False},
                        "response_format":{"type":"json_object", **({"schema":json_schema} if json_schema else {})},
                    })
                    response.raise_for_status()
                choice = response.json()["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise StructuredOutputError("Local ASL output exceeded the token budget")
                text = choice["message"]["content"]
                if not isinstance(text, str) or not text.strip():
                    raise StructuredOutputError("Local ASL returned empty output")
                self._generation_verified, self._last_error = True, None
                return text.strip()
            except StructuredOutputError:
                self._generation_verified = False
                self._last_error = "invalid_model_output"
                raise
            except Exception as exc:
                self._generation_verified = False
                self._last_error = "model_generation_failed"
                logger.exception("Local ASL request failed")
                raise ModelUnavailableError("Local ASL generation failed") from exc
            finally:
                self._last_duration_ms = round((time.perf_counter() - started) * 1000, 2)
