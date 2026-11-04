"""Process entry point: ``tcp-broker`` (``tcp-broker --check`` for health checks)."""

import argparse
import logging
import signal
import sys
import threading
from types import FrameType

from messaging.backends.tcp import DEFAULT_PORT, TcpBroker, TcpBrokerServer
from servicekit import ServiceSettings, configure_logging

log = logging.getLogger(__name__)


class Settings(ServiceSettings):
    service_name: str = "tcp-broker"
    port: int = DEFAULT_PORT


def check(port: int) -> int:
    """Exit 0 if a broker answers on localhost:``port`` (used by the Docker HEALTHCHECK)."""
    try:
        with TcpBroker("127.0.0.1", port, connect_timeout=2.0) as broker:
            broker.ping()
    except Exception as exc:
        print(f"unhealthy: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="ping a running broker and exit")
    args = parser.parse_args(argv)
    settings = Settings()
    if args.check:
        raise SystemExit(check(settings.port))

    configure_logging(settings.service_name, settings.log_level)
    server = TcpBrokerServer(settings.host, settings.port)

    def handle_signal(signum: int, frame: FrameType | None) -> None:
        # shutdown() blocks until serve_forever() returns, so call it off the main thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    log.info("listening on %s:%d", settings.host, server.port)
    with server:
        server.serve_forever()
    log.info("stopped")


if __name__ == "__main__":
    main()
