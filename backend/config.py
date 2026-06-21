from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # LLM Settings
    LLM_PROVIDER: str = "ollama"
    LLM_MODEL: str = "llama3.2:3b"
    LLM_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # RAG Settings (unused but kept for future)
    CHROMA_PERSIST_DIR: str = "./chroma_data"
    EMBEDDING_MODEL: str = "all-minilm"
    DISABLE_RAG: bool = False
    RULE_SCORE_THRESHOLD: float = 0.05

    # Database URL configuration
    DATABASE_URL: str = "postgresql://pardhivkrishna@localhost:5432/iiot_feedback"

    # App Settings
    MAX_TABLES_DEFAULT: int = 3
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=[".env", "backend/.env"], env_file_encoding="utf-8", extra="ignore")

settings = Settings()
