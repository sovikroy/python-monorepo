#!/usr/bin/env python3
"""Scaffold a new deployable service under apps/ following the repo's conventions.

Creates apps/<name>/ (pyproject.toml, Dockerfile, src/<pkg>/, tests/) and wires it into
the workspace: ruff ``known-first-party`` and mypy ``mypy_path`` in the root
pyproject.toml, plus a service entry in compose.yaml. CI needs no change: it discovers
workspace members on its own.

Standard library only, so it runs before ``uv sync``.

Usage:
    scaffold.py <name> --kind http   [--description TEXT] [--broker] [--host-port N]
    scaffold.py <name> --kind worker --event OrderPlaced --topic ORDER_PLACED_TOPIC
    add --dry-run to print what would change without writing anything.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

# --------------------------------------------------------------------------- templates
# Placeholders are __UPPER__ tokens (not $ or {}) so Dockerfile/f-string syntax survives.

PYPROJECT = """\
[project]
name = "__NAME__"
version = "0.1.0"
description = "__DESCRIPTION__"
requires-python = ">=3.13"
__DEPS_COMMENT__dependencies = [__DEPS__]
__BROKER_EXTRAS_TOML__
[project.scripts]
__NAME__ = "__PKG__.main:main"

[tool.uv.sources]
__SOURCES__

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/__PKG__"]
"""

DOCKERFILE = """\
# syntax=docker/dockerfile:1.7
# Build from the repo root so the workspace lockfile and sibling packages are in context:
#   docker build -f apps/__NAME__/Dockerfile -t __NAME__ .
# Only this app and the workspace packages it depends on are installed.
__DOCKER_BROKER_DOC__
ARG PYTHON_VERSION=3.13
ARG APP=__NAME__
__DOCKER_BROKER_ARG__
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder
ARG APP
__DOCKER_BROKER_ARG_STAGE__ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# 1) Third-party deps only (cached layer, rebuilt only when the lock changes).
RUN --mount=type=cache,target=/root/.cache/uv \\
    --mount=type=bind,source=uv.lock,target=uv.lock \\
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \\
    --mount=type=bind,source=packages,target=packages \\
    --mount=type=bind,source=apps,target=apps \\
    uv sync --frozen --no-dev --no-install-workspace --package ${APP}__DOCKER_EXTRA_FLAGS__

# 2) This app + its workspace deps, installed as real (non-editable) wheels.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \\
    uv sync --frozen --no-dev --no-editable --package ${APP}__DOCKER_EXTRA_FLAGS__

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ARG APP
RUN useradd --create-home --uid 1000 app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
__RUNTIME_EXTRA__ENTRYPOINT ["__NAME__"]
"""

HTTP_RUNTIME_EXTRA = """\
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \\
    CMD ["python", "-c", "import urllib.request; \
urllib.request.urlopen('http://localhost:8000/health')"]
"""

INIT = '"""__DESCRIPTION__"""\n'

# ---- http

HTTP_MAIN = '''\
"""Process entry point: ``__NAME__``."""

from __PKG__.app import Settings, build_app
from servicekit import configure_logging
from servicekit.http import serve


def main() -> None:
    settings = Settings()
    configure_logging(settings.service_name, settings.log_level)
    serve(build_app(settings), settings)


if __name__ == "__main__":
    main()
'''

HTTP_APP = '''\
"""HTTP routes for __NAME__. Keep routes thin: validate, call the service, map errors."""

from fastapi import FastAPI

__BROKER_IMPORT__from __PKG__.service import __CLASS__
from servicekit import ServiceSettings
from servicekit.http import create_app


class Settings(ServiceSettings):
    service_name: str = "__NAME__"
__BROKER_SETTING__

def build_app(settings: Settings | None = None, service: __CLASS__ | None = None) -> FastAPI:
    """Build the app. Tests pass a ``service`` wired to fakes; production builds the real one."""
    settings = settings or Settings()
    service = service or __CLASS__(__SERVICE_ARGS__)
    app = create_app(settings)
    app.state.service = service

    # Add routes here, e.g.:
    #
    # @app.get("/things/{thing_id}", tags=["__TAG__"])
    # def get_thing(thing_id: str) -> Thing:
    #     ...

    return app
'''

HTTP_SERVICE = '''\
"""Business logic for __NAME__, kept free of HTTP so it is easy to test."""
__SERVICE_IMPORTS__

class __CLASS__:
    """Depends only on protocols (ports) so tests can pass in-memory fakes."""

    def __init__(self__SERVICE_PARAMS__) -> None:
__SERVICE_BODY__
'''

HTTP_TEST = """\
import pytest
from fastapi.testclient import TestClient

__TEST_BROKER_IMPORT__from __PKG__.app import build_app
from __PKG__.service import __CLASS__


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(service=__CLASS__(__TEST_SERVICE_ARGS__)))


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "__NAME__"
"""

# ---- worker

WORKER_MAIN = '''\
"""Process entry point: ``__NAME__``."""

import signal
import threading
from types import FrameType

from __PKG__.worker import run
from messaging import broker_from_url
from servicekit import ServiceSettings, configure_logging


class Settings(ServiceSettings):
    service_name: str = "__NAME__"
    # The scheme picks the transport: redis://, amqp://, tcp:// or memory://.
    broker_url: str = "redis://localhost:6379/0"


def main() -> None:
    settings = Settings()
    configure_logging(settings.service_name, settings.log_level)
    stop = threading.Event()

    def handle_signal(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    with broker_from_url(settings.broker_url) as broker:
        run(broker, stop)


if __name__ == "__main__":
    main()
'''

WORKER = '''\
"""The consume loop, written so tests can drive it step by step."""

import logging
import threading
from collections.abc import Callable

from contracts import __TOPIC__, __EVENT__
from messaging import Broker, receive_event

log = logging.getLogger(__name__)

Handler = Callable[[__EVENT__], None]


def handle(event: __EVENT__) -> None:
    """Business logic for one event. Replace with what this worker actually does."""
    log.info("received %s", event)


def process_one(broker: Broker, handler: Handler = handle, timeout: float = 1.0) -> bool:
    """Handle at most one event. Returns ``True`` if an event was processed."""
    event = receive_event(broker, __TOPIC__, __EVENT__, timeout=timeout)
    if event is None:
        return False
    handler(event)
    return True


def run(broker: Broker, stop: threading.Event, handler: Handler = handle) -> None:
    """Process events until ``stop`` is set (e.g. on SIGTERM)."""
    log.info("listening on %s", __TOPIC__)
    while not stop.is_set():
        try:
            process_one(broker, handler)
        except Exception:  # keep the worker alive; a real one would dead-letter the event
            log.exception("failed to process event")
            stop.wait(1.0)  # don't spin while the broker is unreachable
    log.info("stopped")
'''

WORKER_TEST = """\
import threading

from __PKG__.worker import process_one, run
from contracts import __TOPIC__
from messaging import InMemoryBroker


def test_process_one_returns_false_when_queue_is_empty() -> None:
    assert process_one(InMemoryBroker(), handler=lambda event: None) is False


def test_run_survives_malformed_messages() -> None:
    broker = InMemoryBroker()
    broker.publish(__TOPIC__, "not json")
    stop = threading.Event()

    def must_not_be_called(event: object) -> None:
        raise AssertionError("a malformed message must not reach the handler")

    def runner() -> None:
        run(broker, stop, handler=must_not_be_called)

    thread = threading.Thread(target=runner)
    thread.start()
    while broker.pending(__TOPIC__):
        pass
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
"""

COMPOSE_HTTP = """
  __NAME__:
    build: { context: ., dockerfile: apps/__NAME__/Dockerfile }
    ports: ["__HOST_PORT__:8000"]
"""

# Uses the anchors defined at the top of compose.yaml, so the service follows whichever
# broker the env file selects (BROKER_URL + COMPOSE_PROFILES).
COMPOSE_BROKER = """\
    environment: *broker-env
    depends_on: *broker-depends
"""

BROKER_EXTRAS_TOML = """
# Broker client libraries, picked at image build time (Dockerfile ARG BROKER_EXTRAS).
# The code only uses the `messaging.Broker` interface; BROKER_URL picks the backend.
[project.optional-dependencies]
redis = ["messaging[redis]"]
rabbitmq = ["messaging[rabbitmq]"]
"""

DOCKER_BROKER_DOC = """#
# BROKER_EXTRAS chooses which broker client libraries go into the image (default: all,
# so BROKER_URL alone picks redis://, amqp:// or tcp://). memory:// and tcp:// need none.
#   docker build --build-arg BROKER_EXTRAS=rabbitmq -f apps/__NAME__/Dockerfile -t __NAME__ .
"""

COMPOSE_WORKER = """
  __NAME__:
    build: { context: ., dockerfile: apps/__NAME__/Dockerfile }
"""


# --------------------------------------------------------------------------- helpers


def render(template: str, values: dict[str, str]) -> str:
    out = template
    for key, value in values.items():
        out = out.replace(f"__{key}__", value)
    leftover = re.findall(r"__[A-Z_]+__", out)
    leftover = [t for t in leftover if t not in ("__name__", "__main__")]
    if leftover:
        raise SystemExit(f"internal error: unfilled placeholders {sorted(set(leftover))}")
    return out


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def append_to_toml_list(text: str, key: str, item: str) -> str:
    """Add ``"item",`` as the last entry of the multi-line TOML list ``key = [ ... ]``."""
    pattern = re.compile(rf"(^{re.escape(key)}\s*=\s*\[\n)(.*?)(^\])", re.M | re.S)
    match = pattern.search(text)
    if match is None:
        fail(f"could not find a multi-line `{key} = [...]` list in pyproject.toml")
        raise AssertionError  # unreachable, for type checkers
    if f'"{item}"' in match.group(2):
        return text
    body = match.group(2) + f'    "{item}",\n'
    return text[: match.start(2)] + body + text[match.end(2) :]


def next_host_port(compose: str) -> int:
    ports = [int(p) for p in re.findall(r'"(\d+):\d+"', compose)]
    return max([8000, *ports]) + 1


def tidy(app_dir: Path) -> None:
    """Sort imports and format the new files (import order depends on the service name)."""
    rel = str(app_dir.relative_to(ROOT))
    for cmd in (["ruff", "check", "--fix", "--select", "I", rel], ["ruff", "format", rel]):
        try:
            subprocess.run(
                ["uv", "run", "--no-sync", *cmd], cwd=ROOT, check=True, capture_output=True
            )
        except (OSError, subprocess.CalledProcessError):
            print(f"  note: could not run `{' '.join(cmd)}`; run it yourself", file=sys.stderr)
            return


def contracts_exports() -> set[str]:
    init = ROOT / "packages/contracts/src/contracts/__init__.py"
    return set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', init.read_text()))


# --------------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="kebab-case service name, e.g. inventory-api")
    parser.add_argument("--kind", choices=["http", "worker"], required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--broker", action="store_true", help="http: inject a Broker to publish")
    parser.add_argument("--host-port", type=int, help="http: host port in compose.yaml")
    parser.add_argument("--event", help="worker: event model exported by contracts")
    parser.add_argument("--topic", help="worker: topic constant exported by contracts")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    name: str = args.name
    if not NAME_RE.match(name):
        fail(f"{name!r} is not kebab-case (lowercase letters, digits, single dashes)")
    pkg = name.replace("-", "_")
    app_dir = ROOT / "apps" / name
    if app_dir.exists():
        fail(f"{app_dir.relative_to(ROOT)} already exists")
    taken = {p.name.replace("-", "_") for d in ("apps", "packages") for p in (ROOT / d).iterdir()}
    if pkg in taken:
        fail(f"import name {pkg!r} is already used by another workspace member")

    is_worker = args.kind == "worker"
    if is_worker:
        if not (args.event and args.topic):
            fail("--kind worker needs --event and --topic (add them to packages/contracts first)")
        missing = {args.event, args.topic} - contracts_exports()
        if missing:
            fail(f"contracts does not export {sorted(missing)}; add them first")
    elif args.event or args.topic:
        fail("--event/--topic only apply to --kind worker")

    class_name = "".join(part.capitalize() for part in name.split("-") if part != "api")
    class_name = (class_name or "App") + "Service"
    description = args.description or (
        f"HTTP service {name}." if not is_worker else f"Background worker {name}."
    )
    description = description.replace('"', "'")
    uses_broker = is_worker or args.broker

    deps = ["contracts"]
    if uses_broker:
        deps.append("messaging")
    deps.append("servicekit" if is_worker else "servicekit[http]")
    sources = "\n".join(f"{d.split('[')[0]} = {{ workspace = true }}" for d in deps)

    values = {
        "NAME": name,
        "PKG": pkg,
        "CLASS": class_name,
        "TAG": name.removesuffix("-api"),
        "DESCRIPTION": description,
        "DEPS": ", ".join(f'"{d}"' for d in deps),
        "DEPS_COMMENT": (
            "# Plain `servicekit` (no `http` extra): this worker has no web server.\n"
            if is_worker
            else ""
        ),
        "SOURCES": sources,
        "BROKER_EXTRAS_TOML": BROKER_EXTRAS_TOML if uses_broker else "",
        "DOCKER_BROKER_DOC": DOCKER_BROKER_DOC.replace("__NAME__", name) if uses_broker else "",
        "DOCKER_BROKER_ARG": 'ARG BROKER_EXTRAS="redis rabbitmq"\n' if uses_broker else "",
        "DOCKER_BROKER_ARG_STAGE": "ARG BROKER_EXTRAS\n" if uses_broker else "",
        "DOCKER_EXTRA_FLAGS": (
            ' $(for e in ${BROKER_EXTRAS}; do printf -- "--extra %s " "$e"; done)'
            if uses_broker
            else ""
        ),
        "RUNTIME_EXTRA": "" if is_worker else HTTP_RUNTIME_EXTRA,
        "EVENT": args.event or "",
        "TOPIC": args.topic or "",
        "BROKER_IMPORT": "from messaging import broker_from_url\n" if args.broker else "",
        "BROKER_SETTING": '    broker_url: str = "memory://"\n' if args.broker else "",
        "SERVICE_ARGS": "broker=broker_from_url(settings.broker_url)" if args.broker else "",
        "SERVICE_IMPORTS": "\nfrom messaging import Broker\n" if args.broker else "",
        "SERVICE_PARAMS": ", broker: Broker" if args.broker else "",
        "SERVICE_BODY": "        self._broker = broker" if args.broker else "        pass",
        "TEST_BROKER_IMPORT": "from messaging import InMemoryBroker\n" if args.broker else "",
        "TEST_SERVICE_ARGS": "broker=InMemoryBroker()" if args.broker else "",
    }
    src = app_dir / "src" / pkg
    files: dict[Path, str] = {
        app_dir / "pyproject.toml": render(PYPROJECT, values),
        app_dir / "Dockerfile": render(DOCKERFILE, values),
        src / "__init__.py": render(INIT, values),
        src / "py.typed": "",
    }
    if is_worker:
        files[src / "main.py"] = render(WORKER_MAIN, values)
        files[src / "worker.py"] = render(WORKER, values)
        files[app_dir / "tests" / f"test_{pkg}.py"] = render(WORKER_TEST, values)
    else:
        files[src / "main.py"] = render(HTTP_MAIN, values)
        files[src / "app.py"] = render(HTTP_APP, values)
        files[src / "service.py"] = render(HTTP_SERVICE, values)
        files[app_dir / "tests" / f"test_{pkg}.py"] = render(HTTP_TEST, values)

    # Root pyproject.toml: ruff first-party + mypy path.
    pyproject_path = ROOT / "pyproject.toml"
    pyproject = pyproject_path.read_text()
    pyproject = append_to_toml_list(pyproject, "known-first-party", pkg)
    pyproject = append_to_toml_list(pyproject, "mypy_path", f"apps/{name}/src")

    # compose.yaml
    compose_path = ROOT / "compose.yaml"
    compose = compose_path.read_text()
    host_port = args.host_port or next_host_port(compose)
    values["HOST_PORT"] = str(host_port)
    block = render(COMPOSE_WORKER if is_worker else COMPOSE_HTTP, values)
    if uses_broker:
        block += COMPOSE_BROKER
    compose = compose.rstrip("\n") + "\n" + block

    changes = [*files, pyproject_path, compose_path]
    if args.dry_run:
        for path, content in files.items():
            print(f"--- would create {path.relative_to(ROOT)}\n{content}")
        print(f"--- would update pyproject.toml (known-first-party += {pkg!r}, mypy_path)")
        print(f"--- would append to compose.yaml:{block}")
        return 0

    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    pyproject_path.write_text(pyproject)
    compose_path.write_text(compose)

    for path in changes:
        print(f"  wrote {path.relative_to(ROOT)}")
    tidy(app_dir)
    if not is_worker:
        print(f"  compose: http://localhost:{host_port}")
    print(
        "\nNext: implement the service, then run\n"
        "  uv sync --all-packages && uv run ruff check . && uv run ruff format --check . "
        f"&& uv run mypy && uv run pytest apps/{name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
