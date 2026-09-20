import os

from dotenv import load_dotenv

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
        role_str = os.getenv("PUBLIC_REGISTER_ROLE", "VIEWER")
        if role_str == "ADMIN":
            raise ValueError("PUBLIC_REGISTER_ROLE cannot be ADMIN")
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

    def effective_jwt_secret_key(self) -> str:
        """Return the JWT signing secret.

        The real secret must come from the environment (JWT_SECRET_KEY). A
        clearly-labelled development-only fallback is used solely so local
        development and tests work before a secret is configured; production
        deployments always fail loudly when the secret is missing.
        """
        secret = self.jwt_secret_key.strip()
        if secret:
            return secret
        if self.environment != "production":
            return _DEV_ONLY_JWT_SECRET
        # Imported lazily to keep the config <-> security import cycle acyclic
        # (security.py imports settings from this module at load time).
        from app.core.security import TokenError

        raise TokenError(
            "JWT_SECRET_KEY must be set in production. Refusing to start with "
            "an empty signing secret."
        )


settings = Settings()