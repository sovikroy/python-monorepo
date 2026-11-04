"""FastAPI app factory used by every HTTP service (needs the ``http`` extra)."""

from typing import Any

import uvicorn
from fastapi import FastAPI

from servicekit.settings import ServiceSettings


def create_app(settings: ServiceSettings, version: str = "0.1.0", **kwargs: Any) -> FastAPI:
    """Create a FastAPI app with the standard ``/health`` endpoint already wired up.

    Container platforms (Docker, Kubernetes, ECS, ...) poll ``/health`` to decide
    whether to route traffic to a replica or restart it.
    """
    app = FastAPI(title=settings.service_name, version=version, **kwargs)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "version": version,
            "environment": settings.environment,
        }

    return app


def serve(app: FastAPI, settings: ServiceSettings) -> None:
    """Run ``app`` with uvicorn using the host/port/log level from ``settings``."""
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
