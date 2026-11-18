import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


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
    auth_token_ttl_seconds: int
    auth_refresh_token_ttl_seconds: int
    ollama_timeout_seconds: float
    job_stale_seconds: int
    cors_origins: tuple[str, ...]
    email_provider: str
    resend_api_key: str | None
    email_from: str
    public_base_url: str


def load_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "development").lower()
    settings = Settings(
        app_env=app_env,
        database_url=os.getenv("DATABASE_URL", "sqlite:///./genai_reviewer.db"),
        auth_secret=os.getenv("AUTH_SECRET", "local-development-secret"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
        redis_url=os.getenv("REDIS_URL") or None,
        prompt_version=os.getenv("PROMPT_VERSION", "v1"),
        auth_token_ttl_seconds=int(os.getenv("AUTH_TOKEN_TTL_SECONDS", "3600")),
        auth_refresh_token_ttl_seconds=int(os.getenv("AUTH_REFRESH_TOKEN_TTL_SECONDS", "2592000")),
        ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
        job_stale_seconds=int(os.getenv("JOB_STALE_SECONDS", "900")),
        cors_origins=tuple(
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
            if origin.strip()
        ),
        email_provider=os.getenv("EMAIL_PROVIDER", "console").lower(),
        resend_api_key=os.getenv("RESEND_API_KEY") or None,
        email_from=os.getenv("EMAIL_FROM", "noreply@example.com"),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
    )
    if settings.app_env == "production":
        if len(settings.auth_secret) < 32 or settings.auth_secret == "local-development-secret":
            raise RuntimeError("Production requires a strong AUTH_SECRET of at least 32 characters")
        if not settings.cors_origins:
            raise RuntimeError("Production requires at least one CORS_ORIGINS entry")
        if settings.email_provider != "resend" or not settings.resend_api_key:
            raise RuntimeError("Production requires EMAIL_PROVIDER=resend and RESEND_API_KEY")
    return settings


settings = load_settings()
