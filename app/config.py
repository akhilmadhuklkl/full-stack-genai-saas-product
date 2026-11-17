import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Runtime configuration loaded from environment variables."""

    app_env: str
    database_url: str
    auth_secret: str
    ollama_base_url: str
    ollama_model: str
    redis_url: str | None
    prompt_version: str


def load_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "development").lower()
    return Settings(
        app_env=app_env,
        database_url=os.getenv("DATABASE_URL", "sqlite:///./genai_reviewer.db"),
        auth_secret=os.getenv("AUTH_SECRET", "local-development-secret"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
        redis_url=os.getenv("REDIS_URL") or None,
        prompt_version=os.getenv("PROMPT_VERSION", "v1"),
    )


settings = load_settings()
