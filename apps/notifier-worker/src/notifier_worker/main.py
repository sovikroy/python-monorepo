"""Process entry point: ``notifier-worker``."""

import signal
import threading
from types import FrameType

from messaging import broker_from_url
from notifier_worker.worker import LogNotifier, run
from servicekit import ServiceSettings, configure_logging


class Settings(ServiceSettings):
    service_name: str = "notifier-worker"
    broker_url: str = "redis://localhost:6379/0"


def main() -> None:
    settings = Settings()
    configure_logging(settings.service_name, settings.log_level)
    stop = threading.Event()

    def handle_signal(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    run(broker_from_url(settings.broker_url), LogNotifier(), stop)


if __name__ == "__main__":
    main()
