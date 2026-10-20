from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings and configuration."""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App Info
    app_name: str = "AI Maintenance Assistant"
    app_env: str = "development"
    debug: bool = True

    # Paths
    base_dir: Path = Path(__file__).resolve().parent.parent
    knowledge_path: str = str(Path(__file__).resolve().parent.parent / "knowledge")
    vectorstore_path: str = str(Path(__file__).resolve().parent.parent / "data" / "vectorstore")
    db_path: str = str(Path(__file__).resolve().parent.parent / "data" / "app.db")
    checkpoints_db_path: str = str(Path(__file__).resolve().parent.parent / "data" / "checkpoints.db")
    seed_path: str = str(Path(__file__).resolve().parent.parent / "data" / "seed" / "assets.json")

    # Local LLM - ASL-4B-v1
    llm_model: str = "saai-sa/ASL-4B-v1"
    llm_revision: str = "79e330632b368ad3d4b919085ab1d6ffaf6d8397"
    llm_mode: Literal["neural", "heuristic"] = "neural"
    llm_engine: Literal["transformers", "llama_cpp"] = "transformers"
    llm_server_executable: str = ""
    llm_gguf_path: str = ""
    llm_server_port: int = 8081
    llm_model_path: str = str(Path(__file__).resolve().parent.parent / "data" / "models" / "ASL-4B-v1")
    llm_runtime_path: str = str(Path(__file__).resolve().parent.parent / ".llm-runtime")
    llm_device: Literal["auto", "cuda", "cpu"] = "auto"
    llm_quantization: Literal["none", "4bit"] = "4bit"
    llm_cpu_threads: int = 6
    llm_max_new_tokens: int = 256
    llm_timeout_seconds: int = 240

    # RAG Settings
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_revision: str = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    embedding_model_path: str = str(Path(__file__).resolve().parent.parent / "data" / "models" / "paraphrase-multilingual-MiniLM-L12-v2")
    rag_cpu_threads: int = 2
    rag_top_k: int = 3
    rag_min_score: float = 0.35


settings = Settings()
