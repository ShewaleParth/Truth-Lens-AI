"""TruthLens AI - Backend Application Entry Point.

Initializes the FastAPI application, mounts middlewares, attaches API routes,
and provides local development server entry.

Phase 2 additions: structured logging configuration.
"""

import logging
import logging.config
from urllib.parse import urlparse
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from backend.api.routes import router as api_router
    from backend.config import get_settings
except ModuleNotFoundError:
    from api.routes import router as api_router  # type: ignore
    from config import get_settings  # type: ignore


def create_app() -> FastAPI:
    """Application factory for TruthLens AI backend."""
    settings = get_settings()
    production = settings.ENVIRONMENT.strip().lower() == "production"
    if production:
        missing_auth_settings = [
            name
            for name, value in (
                ("SUPABASE_URL", settings.SUPABASE_URL),
                ("SUPABASE_PUBLISHABLE_KEY", settings.SUPABASE_PUBLISHABLE_KEY),
            )
            if not value or not value.strip()
        ]
        if missing_auth_settings:
            names = ", ".join(missing_auth_settings)
            raise RuntimeError(
                f"Production startup requires server auth configuration: {names}."
            )
        if settings.DEBUG:
            raise RuntimeError("DEBUG must be false when ENVIRONMENT=production.")
        if not settings.SUPABASE_URL.strip().startswith("https://"):
            raise RuntimeError("SUPABASE_URL must use HTTPS in production.")
        invalid_origins = [
            origin
            for origin in settings.cors_origins_list
            if urlparse(origin).scheme != "https"
            or (urlparse(origin).hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}
        ]
        if invalid_origins:
            raise RuntimeError(
                "CORS_ORIGINS must contain only deployed HTTPS frontend origins in production; "
                "use an empty list for a same-origin deployment."
            )

    # Configure structured logging
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    application = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.DESCRIPTION,
        version=settings.VERSION,
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )

    # Cross-Origin Resource Sharing (CORS) setup
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Authorization", "Content-Type"],
    )

    # Mount API routes with configured prefix (default: /api)
    application.include_router(api_router, prefix=settings.API_PREFIX)

    # In production or unified serving, mount static frontend build if present
    import pathlib
    from fastapi.staticfiles import StaticFiles
    dist_dir = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist_dir.is_dir():
        application.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")

    return application


app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "backend.app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
