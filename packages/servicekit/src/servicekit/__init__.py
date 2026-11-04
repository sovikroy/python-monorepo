"""Plumbing every service needs, so each app only contains its own business logic.

- :class:`ServiceSettings`: configuration from environment variables.
- :func:`configure_logging`: one log format across all services.
- :mod:`servicekit.http` (``servicekit[http]`` extra): FastAPI app factory with
  health checks, plus :func:`~servicekit.http.serve`.
"""

from servicekit.logging import configure_logging
from servicekit.settings import ServiceSettings

__all__ = ["ServiceSettings", "configure_logging"]
