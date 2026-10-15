from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "WeKnora"
    environment: str = "development"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_prefix: str = "/api/v1"
    secret_key: str = "change-me-in-production"
    access_token_minutes: int = 60
    database_url: str = "postgresql+psycopg://weknora:weknora@localhost:5432/weknora"
    redis_url: str = "redis://localhost:6379/0"
    milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "weknora_vectors"
    require_milvus: bool = False
    storage_path: str = "./data/uploads"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_reasoner_model: str = "deepseek-reasoner"
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_api_key: str = ""
    embedding_model: str = "Qwen/Qwen3-VL-Embedding-8B"
    embedding_dimension: int = 4096
    # Rerank is deliberately configured separately from embedding: providers
    # often expose different model names, credentials, or endpoints for the
    # two operations.
    rerank_base_url: str = "https://api.siliconflow.cn/v1"
    rerank_api_key: str = ""
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_enabled: bool = True
    # MCP outbound controls. Private targets are useful in local development
    # but must be explicitly enabled; stdio is an administrator-only feature.
    mcp_allow_private_hosts: bool = False
    mcp_allow_stdio: bool = False
    max_upload_mb: int = 50
    # The documented CLI is launched from ``backend/``, while the project
    # keeps its local secrets in the repository-root ``.env``. Support both
    # locations; real process environment variables still take precedence.
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", ".env"),
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def validate_runtime_configuration(self) -> None:
        if self.environment.lower() in {"production", "staging"}:
            if self.secret_key == "change-me-in-production" or len(self.secret_key) < 32:
                raise RuntimeError("SECRET_KEY must be explicitly set to a random value of at least 32 characters")
            if not self.require_milvus:
                raise RuntimeError("REQUIRE_MILVUS must be enabled outside development")


@lru_cache
def get_settings() -> Settings:
    return Settings()
