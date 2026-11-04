#!/usr/bin/env python3
"""Scaffold a new message-broker backend (transport) for packages/messaging.

Creates the backend module and its test file, then wires the backend into every place a
broker appears, so that only the transport logic and the docs are left to write:

- packages/messaging: ``_BACKENDS`` / ``_EXTRAS`` / module docstring in ``broker.py``,
  the optional extra in ``pyproject.toml``, and ``REAL_BROKERS`` in ``tests/conftest.py``
- root pyproject.toml: the client library in the ``dev`` group (and a mypy override)
- every app that carries broker extras: its extra and its Dockerfile ``BROKER_EXTRAS``
- compose.yaml: the ``BROKER_EXTRAS`` defaults, a broker service with its own profile,
  and the ``x-broker-depends`` anchor; plus ``brokers/<name>.env``
- .github/workflows/ci.yml: a service container and test URL in the ``brokers`` job, and
  the broker in the ``compose`` matrix

The new-service scaffold reads the broker extras from packages/messaging, so new services
pick the backend up automatically.

Standard library only, so it runs before ``uv sync``.

Usage:
    scaffold.py nats --title NATS --dependency "nats-py>=2.9" \\
        --image nats:2-alpine --port 4222 --healthcheck "wget -q -O- localhost:8222/healthz"
    scaffold.py <name> --scheme <s> [--scheme <s2>] ...   (default scheme: <name>)
    add --dry-run to print a diff of every change without writing anything.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
MESSAGING = ROOT / "packages/messaging"
NAME_RE = re.compile(r"^[a-z][a-z0-9]*$")
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*$")
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")

# --------------------------------------------------------------------------- templates
# Placeholders are __UPPER__ tokens so Python and YAML syntax survives.

BACKEND = '''\
"""__TITLE__ backend: TODO say how topics map onto __TITLE__ (e.g. one queue per topic).

TODO describe the delivery guarantee (compare the Redis and RabbitMQ backends, which are
at-most-once: a message is removed from the queue as soon as it is received).

Contract every backend must keep (``messaging.Broker``, tests/test_messaging.py):

- ``publish(topic, message)``: when it returns, the server has accepted the message.
- ``receive(topic, timeout)``: the next message on ``topic``, delivered to exactly one
  consumer even with many replicas (work-queue semantics, not fan-out), FIFO per topic;
  ``None`` once ``timeout`` seconds pass without one.
- ``close()``: releases the connection and is safe to call more than once.
- Thread-safe: FastAPI runs sync routes on a thread pool, so guard a shared connection.
- ``from_url`` must not connect (the registry tests build every backend offline);
  connect on first use and reconnect once if the link has dropped.
"""

from __future__ import annotations

import threading
from typing import Self

from messaging.broker import Broker


class __CLASS__(Broker):
    def __init__(self, url: str) -> None:
        self._url = url
        self._lock = threading.Lock()

    @classmethod
    def from_url(cls, url: str) -> Self:
        return cls(url)

    def publish(self, topic: str, message: str) -> None:
        raise NotImplementedError("TODO: publish with the __TITLE__ client")

    def receive(self, topic: str, timeout: float = 1.0) -> str | None:
        raise NotImplementedError("TODO: receive with the __TITLE__ client")

    def close(self) -> None:
        pass
'''

BACKEND_TEST = '''\
"""__TITLE__-specific behaviour.

The shared contract tests (test_messaging.py) also run against a real server when
__ENV__ is set, as CI's broker integration job does:

    __ENV__=__TEST_URL__ uv run pytest packages/messaging
"""

import os

import pytest

from messaging import broker_from_url
from messaging.backends.__MODULE__ import __CLASS__

URL = os.environ.get("__ENV__")


@pytest.mark.parametrize("url", [__SCHEME_URLS__])
def test_url_selects___MODULE__(url: str) -> None:
    # Building a broker never connects; the first publish/receive does.
    with broker_from_url(url) as broker:
        assert isinstance(broker, __CLASS__)


@pytest.mark.skipif(not URL, reason="__ENV__ not set")
def test_messages_wait_for_a_later_consumer(topic: str) -> None:
    assert URL
    with broker_from_url(URL) as producer:
        producer.publish(topic, "queued")
    with broker_from_url(URL) as consumer:
        assert consumer.receive(topic, timeout=2) == "queued"
'''

ENV_FILE = """\
# docker compose --env-file brokers/__NAME__.env up --build
COMPOSE_PROFILES=__NAME__
BROKER_URL=__COMPOSE_URL__
"""


# --------------------------------------------------------------------------- helpers


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def render(template: str, values: dict[str, str]) -> str:
    out = template
    for key, value in values.items():
        out = out.replace(f"__{key}__", value)
    return out


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


class Changes:
    """New file contents, keyed by path; edits to one file accumulate."""

    def changed(self) -> dict[Path, str]:
        return {p: c for p, c in self.files.items() if p in self.created or c != p.read_text()}

    def __init__(self) -> None:
        self.files: dict[Path, str] = {}
        self.created: set[Path] = set()

    def text(self, path: Path) -> str:
        if path not in self.files:
            self.files[path] = path.read_text()
        return self.files[path]

    def set(self, path: Path, content: str) -> None:
        self.text(path)
        self.files[path] = content

    def create(self, path: Path, content: str) -> None:
        if path.exists():
            fail(f"{rel(path)} already exists")
        self.files[path] = content
        self.created.add(path)


def sub_once(text: str, pattern: str, repl: str, where: str, flags: int = re.M) -> str:
    """Apply a regex substitution that must match exactly once, or stop with an error."""
    new, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        fail(f"could not find where to edit {where}; edit it by hand (see SKILL.md)")
    return new


def tidy(paths: list[Path]) -> None:
    """Sort imports and format the edited Python files (long lines get wrapped)."""
    files = [rel(p) for p in paths if p.suffix == ".py"]
    for cmd in (["ruff", "check", "--fix", "--select", "I", *files], ["ruff", "format", *files]):
        try:
            subprocess.run(
                ["uv", "run", "--no-sync", *cmd], cwd=ROOT, check=True, capture_output=True
            )
        except (OSError, subprocess.CalledProcessError):
            print(f"  note: could not run `{' '.join(cmd[:2])}`; run it yourself", file=sys.stderr)
            return


# --------------------------------------------------------------------------- edits


def edit_registry(ch: Changes, a: argparse.Namespace) -> None:
    path = MESSAGING / "src/messaging/broker.py"
    text = ch.text(path)
    backends = re.search(r"^_BACKENDS: .*? = \{\n(.*?)^\}", text, re.M | re.S)
    if backends is None:
        fail("could not find `_BACKENDS = {...}` in broker.py")
        raise AssertionError  # unreachable, for type checkers
    for scheme in a.schemes:
        if re.search(rf'^\s*"{re.escape(scheme)}":', backends.group(1), re.M):
            fail(f"scheme {scheme!r} is already registered in broker.py")
    entries = "".join(
        f'    "{s}": "messaging.backends.{a.module}:{a.class_name}",\n' for s in a.schemes
    )
    text = text[: backends.end(1)] + entries + text[backends.end(1) :]

    if a.dependency:
        entry = rf'\1, "{a.module}": "{a.name}"}}'
        text = sub_once(text, r"^(_EXTRAS = \{.*?)\}", entry, "_EXTRAS in broker.py")

    # Module docstring: the list of example URLs, one per backend.
    doc_end = text.index('"""', 3)
    lines = text[:doc_end].split("\n")
    url_rows = [i for i, line in enumerate(lines) if re.match(r"^    \S+://", line)]
    if url_rows:
        last = lines[url_rows[-1]]
        column = len(last) - len(last.split("://", 1)[1].split(" ", 1)[1].lstrip())
        url = a.compose_url or f"{a.schemes[0]}://..."
        note = f"{a.title} (needs messaging[{a.name}])" if a.dependency else a.title
        lines.insert(url_rows[-1] + 1, f"    {url}".ljust(max(column, len(url) + 6)) + note)
        text = "\n".join(lines) + text[doc_end:]
    ch.set(path, text)


def edit_messaging_pyproject(ch: Changes, a: argparse.Namespace) -> None:
    if not a.dependency:
        return
    path = MESSAGING / "pyproject.toml"
    text = ch.text(path)
    if re.search(rf"^{a.name}\s*=", text, re.M):
        fail(f"packages/messaging already has an extra named {a.name!r}")
    text = sub_once(
        text,
        r"(^\[project\.optional-dependencies\]\n(?:[^\n\[][^\n]*\n)*)",
        rf'\g<1>{a.name} = ["{a.dependency}"]\n',
        "[project.optional-dependencies] in packages/messaging/pyproject.toml",
    )
    ch.set(path, text)


def edit_root_pyproject(ch: Changes, a: argparse.Namespace) -> None:
    path = ROOT / "pyproject.toml"
    text = ch.text(path)
    if a.dependency:
        text = sub_once(
            text,
            r"(^    # Every broker client.*\n)",
            rf'\g<1>    "{a.dependency}",\n',
            'the "# Every broker client" comment in the dev group of pyproject.toml',
        )
    if a.untyped:
        override = (
            "[[tool.mypy.overrides]]\n"
            f'module = ["{a.client_import}", "{a.client_import}.*"]  # ships no type hints\n'
            "ignore_missing_imports = true\n\n"
        )
        text = sub_once(
            text,
            r"(^# -+ pytest\n)",
            override.replace("\\", "\\\\") + r"\1",
            "the pytest section of pyproject.toml",
        )
    ch.set(path, text)


def edit_apps(ch: Changes, a: argparse.Namespace) -> list[str]:
    """Give every app that carries broker extras the new one too."""
    touched = []
    if not a.dependency:
        return touched
    for pyproject in sorted(ROOT.glob("apps/*/pyproject.toml")):
        text = ch.text(pyproject)
        rows = list(re.finditer(r'^\w+ = \["messaging\[\w+\]"\]\n', text, re.M))
        if not rows:
            continue
        end = rows[-1].end()
        ch.set(pyproject, text[:end] + f'{a.name} = ["messaging[{a.name}]"]\n' + text[end:])
        dockerfile = pyproject.parent / "Dockerfile"
        if dockerfile.exists():
            ch.set(
                dockerfile,
                sub_once(
                    ch.text(dockerfile),
                    r'^(ARG BROKER_EXTRAS=")([^"]*)"',
                    rf'\1\2 {a.name}"',
                    f"ARG BROKER_EXTRAS in {rel(dockerfile)}",
                ),
            )
        touched.append(pyproject.parent.name)
    return touched


def edit_compose(ch: Changes, a: argparse.Namespace) -> None:
    path = ROOT / "compose.yaml"
    text = ch.text(path)
    if a.dependency:
        text = re.sub(r"\$\{BROKER_EXTRAS:-([^}]*)\}", rf"${{BROKER_EXTRAS:-\1 {a.name}}}", text)
    if a.image:
        if re.search(rf"^  {re.escape(a.name)}:\s*$", text, re.M):
            fail(f"compose.yaml already has a service named {a.name!r}")
        block = [f"  {a.name}:", f"    profiles: [{a.name}]", f"    image: {a.image}"]
        if a.container_env:
            block.append("    environment:")
            block += [f"      {k}: {json.dumps(v)}" for k, v in a.container_env]
        if a.healthcheck:
            block += [
                "    healthcheck:",
                f'      test: ["CMD-SHELL", {json.dumps(a.healthcheck)}]',
                "      interval: 5s",
                "      timeout: 10s",
                "      retries: 12",
            ]
        text = sub_once(
            text,
            r"(^  # -+ services\n)",
            "\n".join(block).replace("\\", "\\\\") + r"\n\n\1",
            "the `# --- services` marker in compose.yaml",
        )
        condition = "service_healthy" if a.healthcheck else "service_started"
        text = sub_once(
            text,
            r"(^x-broker-depends: &broker-depends\n(?:  .*\n)*)",
            rf"\g<1>  {a.name}: {{ condition: {condition}, required: false }}\n",
            "the x-broker-depends anchor in compose.yaml",
        )
    ch.set(path, text)


def edit_conftest(ch: Changes, a: argparse.Namespace) -> None:
    path = MESSAGING / "tests/conftest.py"
    ch.set(
        path,
        sub_once(
            ch.text(path),
            r"(^REAL_BROKERS = \{\n(?:    .*\n)*)",
            rf'\g<1>    "{a.name}": "{a.test_env}",\n',
            "REAL_BROKERS in packages/messaging/tests/conftest.py",
        ),
    )


def edit_ci(ch: Changes, a: argparse.Namespace) -> None:
    path = ROOT / ".github/workflows/ci.yml"
    if not path.exists() or not a.image:
        return
    text = ch.text(path)
    job = re.search(r"^  brokers:\n(?:(?:    .*|[ \t]*)\n)*", text, re.M)
    if job is None:
        fail("could not find the `brokers` job in ci.yml")
        raise AssertionError  # unreachable, for type checkers
    body = job.group(0)
    service = [
        f"      {a.name}:",
        f"        image: {a.image}",
        f'        ports: ["{a.port}:{a.port}"]',
    ]
    if a.container_env:
        service.append("        env:")
        service += [f"          {k}: {json.dumps(v)}" for k, v in a.container_env]
    if a.healthcheck:
        service += [
            "        options: >-",
            f"          --health-cmd {json.dumps(a.healthcheck)} --health-interval 5s",
            "          --health-timeout 10s --health-retries 20",
        ]
    body = sub_once(
        body,
        r"(^    steps:\n)",
        "\n".join(service).replace("\\", "\\\\") + r"\n\1",
        "`steps:` of the brokers job in ci.yml",
    )
    rows = list(re.finditer(r"^          MESSAGING_TEST_\w+: .*\n", body, re.M))
    if not rows:
        fail("could not find the MESSAGING_TEST_* env vars of the brokers job in ci.yml")
    end = rows[-1].end()
    body = body[:end] + f"          {a.test_env}: {a.test_url}\n" + body[end:]
    body = re.sub(r"(name: Broker integration \([^)]*)\)", rf"\1 + {a.title})", body, count=1)
    text = text[: job.start()] + body + text[job.end() :]
    text = sub_once(
        text,
        r"^(        broker: \[)([^\]]*)\]",
        rf"\1\2, {a.name}]",
        "the compose job's broker matrix in ci.yml",
    )
    ch.set(path, text)


# --------------------------------------------------------------------------- main


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="short lowercase id: extra, compose service, env file")
    parser.add_argument("--title", help="display name, e.g. NATS (default: Name)")
    parser.add_argument("--scheme", action="append", dest="schemes", help="URL scheme (repeatable)")
    parser.add_argument("--class", dest="class_name", help="default: <Title>Broker")
    parser.add_argument("--module", help="module under messaging/backends (default: name)")
    parser.add_argument("--dependency", help='client library requirement, e.g. "nats-py>=2.9"')
    parser.add_argument("--client-import", help="top-level import name of the client library")
    parser.add_argument("--untyped", action="store_true", help="add a mypy ignore override")
    parser.add_argument("--image", help="Docker image of the server (compose + CI)")
    parser.add_argument("--port", type=int, help="the server's client port (with --image)")
    parser.add_argument("--healthcheck", help="shell command that succeeds once it is ready")
    parser.add_argument(
        "--container-env", action="append", default=[], help="KEY=VALUE for the server"
    )
    parser.add_argument("--compose-url", help="BROKER_URL inside compose")
    parser.add_argument("--test-url", help="URL the integration tests use (from the host)")
    parser.add_argument("--test-env", help="default: MESSAGING_TEST_<NAME>_URL")
    parser.add_argument("--dry-run", action="store_true")
    a = parser.parse_args()

    if not NAME_RE.match(a.name):
        fail(f"{a.name!r} must be lowercase letters and digits, e.g. nats or sqs")
    a.title = a.title or a.name.capitalize()
    a.schemes = [s.lower() for s in (a.schemes or [a.name])]
    for scheme in a.schemes:
        if not SCHEME_RE.match(scheme):
            fail(f"{scheme!r} is not a valid URL scheme")
    a.module = a.module or a.name
    if not a.module.isidentifier():
        fail(f"--module {a.module!r} is not a Python identifier")
    a.class_name = a.class_name or re.sub(r"\W", "", a.title.title()) + "Broker"
    if not a.class_name.isidentifier():
        fail(f"--class {a.class_name!r} is not a Python identifier")
    if a.untyped and not a.client_import:
        fail("--untyped needs --client-import (the module mypy should ignore)")
    if a.image and not a.port:
        fail("--image needs --port (the port clients connect to)")
    if a.healthcheck and '"' in a.healthcheck:
        fail("--healthcheck must not contain double quotes")
    for item in a.container_env:
        if not ENV_RE.match(item):
            fail(f"--container-env {item!r} is not KEY=VALUE")
    a.container_env = [tuple(item.split("=", 1)) for item in a.container_env]
    if a.image:
        a.compose_url = a.compose_url or f"{a.schemes[0]}://{a.name}:{a.port}"
        a.test_url = a.test_url or f"{a.schemes[0]}://localhost:{a.port}"
    a.test_env = a.test_env or f"MESSAGING_TEST_{a.name.upper()}_URL"
    return a


def main() -> int:
    a = parse_args()
    backend = MESSAGING / f"src/messaging/backends/{a.module}.py"
    test = MESSAGING / f"tests/test_{a.module}.py"
    if backend.exists():
        fail(f"{rel(backend)} already exists; pick another name or --module")
    clash = [p for p in ROOT.glob(f"*/*/tests/**/{test.name}") if ".venv" not in p.parts]
    if clash:
        fail(f"{rel(clash[0])} exists; test file names must be unique (use --module)")

    values = {
        "TITLE": a.title,
        "CLASS": a.class_name,
        "MODULE": a.module,
        "NAME": a.name,
        "ENV": a.test_env,
        "TEST_URL": a.test_url or f"{a.schemes[0]}://localhost",
        "COMPOSE_URL": a.compose_url or "",
        "SCHEME_URLS": ", ".join(json.dumps(f"{s}://localhost") for s in a.schemes),
    }
    ch = Changes()
    ch.create(backend, render(BACKEND, values))
    ch.create(test, render(BACKEND_TEST, values))
    edit_registry(ch, a)
    edit_messaging_pyproject(ch, a)
    edit_root_pyproject(ch, a)
    apps = edit_apps(ch, a)
    edit_compose(ch, a)
    edit_conftest(ch, a)
    edit_ci(ch, a)
    if a.compose_url:
        ch.create(ROOT / f"brokers/{a.name}.env", render(ENV_FILE, values))

    if a.dry_run:
        for path, new in ch.changed().items():
            old = "" if path in ch.created else path.read_text()
            sys.stdout.writelines(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    new.splitlines(keepends=True),
                    "/dev/null" if path in ch.created else f"a/{rel(path)}",
                    f"b/{rel(path)}",
                )
            )
        return 0

    changed = ch.changed()
    for path, content in changed.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"  {'created' if path in ch.created else 'updated'} {rel(path)}")
    tidy(list(changed))

    print(f"\nRegistered {', '.join(s + '://' for s in a.schemes)} -> {a.class_name}.")
    if apps:
        print(f"Broker extra `{a.name}` added to: {', '.join(apps)}.")
    if not a.image:
        print("No --image: compose.yaml and CI have no server for it; see SKILL.md step 3.")
    print(
        f"\nNext: implement {rel(backend)}, then run\n"
        "  uv lock && uv sync --all-packages && uv run ruff check . && uv run mypy "
        "&& uv run pytest packages/messaging"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
