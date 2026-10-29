"""TruthLens AI - Centralized Application Configuration.

Manages environment-driven settings, sensible local development defaults,
and application metadata.  Updated in Phase 2 to add search provider,
timeout, and database configuration without breaking Phase 1 settings.
"""

import pathlib
from functools import lru_cache
from typing import List, Optional, Union
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent
_ROOT_DIR = _BACKEND_DIR.parent


class Settings(BaseSettings):
    """Application settings with safe local defaults and environment overrides."""

    model_config = SettingsConfigDict(
        env_file=(
            str(_ROOT_DIR / ".env"),
            str(_BACKEND_DIR / ".env"),
            ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # Core Application Metadata
    PROJECT_NAME: str = "TruthLens AI"
    VERSION: str = "0.1.0"
    DESCRIPTION: str = (
        "AI-powered financial misinformation and scam intelligence platform."
    )
    API_PREFIX: str = "/api"

    # Runtime Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Server Networking
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # Cross-Origin Resource Sharing (CORS)
    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Supabase Auth server-side token validation. These are project configuration
    # values; the publishable key is not a service-role secret.
    SUPABASE_URL: Optional[str] = None
    SUPABASE_PUBLISHABLE_KEY: Optional[str] = None

    # ── Multi-Provider Evidence Search Configuration ─────────────────────

    # API keys for official search providers (optional; disabled if unset)
    TAVILY_API_KEY: Optional[str] = None
    SERPER_API_KEY: Optional[str] = None

    # Priority order: tavily, serper, duckduckgo. A `none`/`noop` entry
    # disables all external search.
    SEARCH_PROVIDER_ORDER: Union[List[str], str] = "serper,duckduckgo"

    # When true, queries multiple providers for corroboration rather than stopping at the first success
    SEARCH_CORROBORATE_PROVIDERS: bool = False

    # Per-request analysis timeout in seconds (safety guard; not yet enforced
    # at the HTTP layer but used by individual service calls).
    REQUEST_TIMEOUT_SECONDS: float = 15.0

    # Per-process analysis rate limit. A shared gateway limiter is required when
    # running multiple workers/replicas.
    ANALYZE_RATE_LIMIT_REQUESTS: int = 10
    ANALYZE_RATE_LIMIT_WINDOW_SECONDS: int = 60

    # Maximum claim input length in characters (mirrors claim_processor constant).
    MAX_INPUT_LENGTH: int = 5_000

    # SQLite database path for verification history (Phase 7).
    # Set to ':memory:' for ephemeral in-memory storage (tests).
    DATABASE_URL: str = "sqlite:///truthlens.db"

    # Logging level: DEBUG, INFO, WARNING, ERROR.
    LOG_LEVEL: str = "INFO"

    @property
    def cors_origins_list(self) -> List[str]:
        """Return CORS origins as a list of strings."""
        if isinstance(self.CORS_ORIGINS, list):
            return self.CORS_ORIGINS
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def search_provider_order_list(self) -> List[str]:
        """Return search provider order as a list of cleaned, lowercase names."""
        if isinstance(self.SEARCH_PROVIDER_ORDER, list):
            return [p.strip().lower() for p in self.SEARCH_PROVIDER_ORDER if p.strip()]
        return [
            p.strip().lower()
            for p in self.SEARCH_PROVIDER_ORDER.split(",")
            if p.strip()
        ]


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings."""
    return Settings()
