"""Centralised runtime configuration loaded from environment / .env files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings.

    Values are read from environment variables or a `.env` file at the
    repository root. See `.env.example` for the full list and defaults.
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    llm_provider: Literal["ollama", "openai_compatible"] = "ollama"

    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "llama3"
    ollama_timeout_seconds: float = 120.0

    # OpenAI-compatible local server (LM Studio, llama.cpp `--server`,
    # vLLM, Jan, etc.). Default port matches LM Studio's local server.
    openai_compatible_base_url: str = "http://localhost:1234/v1"
    openai_compatible_model: str = ""  # empty -> use whatever model is loaded
    openai_compatible_api_key: str = "lm-studio"
    openai_compatible_timeout_seconds: float = 120.0

    # Embeddings. "default" uses ChromaDB's bundled all-MiniLM-L6-v2
    # (English-only). "openai_compatible" hits a /v1/embeddings endpoint
    # (recommended; LM Studio's nomic-embed-text-v1.5 is multilingual and
    # works for Sanskrit/Devanagari). "ollama" hits Ollama's /api/embed.
    embedding_provider: Literal["default", "openai_compatible", "ollama"] = "default"
    embedding_base_url: str = ""  # empty -> reuse the matching LLM provider URL
    embedding_model: str = "text-embedding-nomic-embed-text-v1.5"
    embedding_api_key: str = ""  # empty -> reuse openai_compatible_api_key
    embedding_timeout_seconds: float = 60.0

    database_url: str = f"sqlite:///{PROJECT_ROOT / 'vedanta.db'}"
    chroma_persist_dir: str = str(PROJECT_ROOT / "data" / "chroma")

    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    instagram_page_token: str = ""
    instagram_verify_token: str = ""

    secret_key: str = "dev-only-change-me"
    encryption_key: str = "dev-only-change-me"

    admin_email: str = ""
    local_timezone: str = "Asia/Kolkata"

    app_host: str = "127.0.0.1"
    app_port: int = 8000

    cors_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated list of allowed CORS origins.",
    )

    @property
    def sqlite_path(self) -> Path:
        """Return the on-disk path for the SQLite database."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return Path(self.database_url[len(prefix):])
        return PROJECT_ROOT / "vedanta.db"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor so the .env is only parsed once per process."""
    return Settings()
