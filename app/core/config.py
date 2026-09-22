import os

from dotenv import load_dotenv

from app.models.user import PUBLIC_REGISTRATION_ROLES

load_dotenv()

_DEV_ONLY_JWT_SECRET = "dev-only-insecure-secret-change-me-0123456789"

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
        self.jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "")
        self.jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
        self.access_token_expire_minutes: int = int(
            os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
        )
        role_str = os.getenv("PUBLIC_REGISTER_ROLE", "VIEWER").strip().upper()
        allowed_public_roles = sorted(
            role.value for role in PUBLIC_REGISTRATION_ROLES
        )
        if role_str not in allowed_public_roles:
            raise ValueError(
                "PUBLIC_REGISTER_ROLE must be one of the public registration "
                f"roles {allowed_public_roles}; got '{role_str}'"
            )
        self.public_register_role: str = role_str
        self.seed_dev_admin: bool = os.getenv("SEED_DEV_ADMIN", "false").lower() in (
            _DEV_TRUTHY
        )
        self.dev_admin_username: str = os.getenv(
            "DEV_ADMIN_USERNAME", "dev_admin"
        )
        self.dev_admin_password: str = os.getenv(
            "DEV_ADMIN_PASSWORD", "dev_admin_password"
        )
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

    def effective_jwt_secret_key(self) -> str:
        """Return the JWT signing secret, failing closed outside development.

        The real secret always comes from the environment (JWT_SECRET_KEY).
        A clearly-labelled development-only fallback is used solely so local
        development works before a secret is configured. Outside the exact
        ``development`` environment an explicitly configured, non-default
        secret is required: any other environment (production, staging, ...)
        fails closed rather than silently signing tokens with a predictable
        key. The secret value is never logged or echoed in the error.
        """
        if self.environment == "development":
            # Development may intentionally run without a configured secret.
            return self.jwt_secret_key.strip() or _DEV_ONLY_JWT_SECRET

        # Imported lazily to keep the config <-> security import cycle acyclic
        # (security.py imports settings from this module at load time).
        from app.core.security import TokenError

        secret = self.jwt_secret_key.strip()
        if not secret:
            raise TokenError(
                "JWT_SECRET_KEY must be set outside development. Refusing to "
                "start with an empty or default signing secret."
            )
        if secret == _DEV_ONLY_JWT_SECRET:
            raise TokenError(
                "The development JWT signing secret cannot be used outside "
                "development. Configure a real JWT_SECRET_KEY."
            )
        return secret


settings = Settings()


def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return settings
