import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self) -> None:
        self.app_name: str = os.getenv(
            "APP_NAME", "Humanitarian Needs Assessment API"
        )
        self.app_version: str = os.getenv("APP_VERSION", "0.1.0")
        self.environment: str = os.getenv("ENVIRONMENT", "development")
        self.debug: bool = os.getenv("DEBUG", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.cors_origins: list[str] = [
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "*").split(",")
        ]
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.geocoder_provider: str = os.getenv("GEOCODER_PROVIDER", "stub")


settings = Settings()