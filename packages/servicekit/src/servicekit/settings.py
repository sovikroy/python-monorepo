"""Environment-driven settings shared by all services."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class ServiceSettings(BaseSettings):
    """Base settings. Subclass it and add service-specific fields.

    Every field can be set from an environment variable of the same name
    (case-insensitive), e.g. ``PORT=9000`` or ``LOG_LEVEL=DEBUG``.
    """

    model_config = SettingsConfigDict(extra="ignore")

    service_name: str = "service"
    environment: str = "local"
    log_level: LogLevel = "INFO"
    host: str = "0.0.0.0"  # listen on all interfaces inside containers
    port: int = 8000
