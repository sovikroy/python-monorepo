"""Process entry point: ``orders-api``."""

from orders_api.app import Settings, build_app
from servicekit import configure_logging
from servicekit.http import serve


def main() -> None:
    settings = Settings()
    configure_logging(settings.service_name, settings.log_level)
    serve(build_app(settings), settings)


if __name__ == "__main__":
    main()
