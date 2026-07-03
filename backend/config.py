from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    app_env: str = "demo"
    llm_enabled: bool = False
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-5.5"
    embedding_model: str = "text-embedding-3-small"
    backend_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    data_dir: Path = BACKEND_ROOT / "data"
    knowledge_base_dir: Path = BACKEND_ROOT / "knowledge_base"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def vector_index_path(self) -> Path:
        return self.data_dir / "vector_index.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
