import os

from dotenv import load_dotenv

load_dotenv()

_DEV_TRUTHY = {"1", "true", "yes", "on"}


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self) -> None:
        self.app_name: str = os.getenv(
            "APP_NAME", "Humanitarian Needs Assessment API"
        )
        self.app_version: str = os.getenv("APP_VERSION", "0.1.0")
        self.environment: str = os.getenv("ENVIRONMENT", "development")
        self.cors_origins: list[str] = [
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "*").split(",")
        ]
        if self.environment == "production" and "*" in self.cors_origins:
            raise ValueError("Wildcard CORS (*) is not allowed in production")
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
        self.database_url: str = os.getenv("DATABASE_URL", "")
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.ai_max_retries: int = int(os.getenv("AI_MAX_RETRIES", "2"))
        if self.ai_max_retries < 0:
            raise ValueError("AI_MAX_RETRIES cannot be negative")
        self.ai_retry_backoff_seconds: float = float(
            os.getenv("AI_RETRY_BACKOFF_SECONDS", "0.5")
        )
        self.geocoder_provider: str = os.getenv("GEOCODER_PROVIDER", "stub")
        self.use_persistent_db: bool = os.getenv("USE_PERSISTENT_DB", "true").lower() in (
            _DEV_TRUTHY
        )
        self.data_dir: str = os.getenv("DATA_DIR", "data")
        self.db_create_tables_on_startup: bool = os.getenv(
            "DB_CREATE_TABLES_ON_STARTUP", "false"
        ).lower() in (_DEV_TRUTHY)
        # Enforce schema readiness at startup whenever the application is
        # database-backed OUTSIDE development: a production app must never
        # silently operate against an incomplete Phase 15 schema. Operator-set
        # DB_ENFORCE_SCHEMA_READY=true/false overrides the environment default.
        raw_schema_ready = os.getenv("DB_ENFORCE_SCHEMA_READY")
        if raw_schema_ready is None:
            self.enforce_schema_ready: bool = self.environment != "development"
        else:
            self.enforce_schema_ready: bool = raw_schema_ready.strip().lower() in (
                _DEV_TRUTHY
            )


settings = Settings()


def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return settings
