from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración leída de variables de entorno (y de .env si existe)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str

    upload_dir: str = "/data/uploads"
    max_upload_mb: int = Field(default=20, gt=0)
    max_pages: int = Field(default=500, gt=0)

    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_provider: Literal["fastembed", "fake"] = "fastembed"
    embedding_cache_dir: str | None = None
    embedding_batch_size: int = Field(default=32, gt=0)

    chunk_size: int = Field(default=1000, ge=200)
    chunk_overlap: int = Field(default=150, ge=0)
    retrieval_k: int = Field(default=6, gt=0, le=50)
    similarity_threshold: float = Field(default=0.35, ge=0.0, le=1.0)

    llm_provider: Literal["mock", "openai"] = "mock"
    openai_api_key: SecretStr | None = None
    openai_model: str = ""
    llm_timeout_seconds: float = Field(default=30.0, gt=0)

    otel_enabled: bool = True
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    log_level: str = "INFO"

    default_org_id: str = "default"
    stuck_after_minutes: int = Field(default=10, gt=0)
    max_ingest_attempts: int = Field(default=5, gt=0)

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP debe ser menor que CHUNK_SIZE")
        if self.llm_provider == "openai" and (self.openai_api_key is None or not self.openai_model):
            raise ValueError("LLM_PROVIDER=openai requiere OPENAI_API_KEY y OPENAI_MODEL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
