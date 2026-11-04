"""Uniform logging setup."""

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s [{service}] %(name)s: %(message)s"


def configure_logging(service_name: str, level: str = "INFO") -> None:
    """Send logs to stdout (where container platforms collect them) in one shared format."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT.format(service=service_name)))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
