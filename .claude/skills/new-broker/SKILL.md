---
name: new-broker
description: Add a new message-broker backend (transport) to packages/messaging - such as NATS, SQS, Kafka, Pulsar or a custom protocol - fully wired in: Broker subclass, URL scheme, optional client-library extra, app extras and Dockerfiles, compose profile and env file, contract tests and CI, and docs - and verified with ruff, mypy and pytest. Use when the user asks to add, create, support or plug in a new broker, transport, message queue or BROKER_URL scheme.
---

# Add a new broker backend

Services only see `messaging.Broker`; `BROKER_URL`'s scheme picks the backend at start-up
(see `ARCHITECTURE.md`, "Pluggable transport"). A new backend touches a dozen files, so a
scaffold script does the wiring and you write the transport logic, tests and docs.
**No service code changes.** If you find yourself editing `apps/*/src`, stop and rethink.

## 1. Check that the transport fits the contract

Every backend must keep the behaviour in `packages/messaging/tests/test_messaging.py`:

- **Work queue**: each message goes to exactly one consumer, even with many worker replicas
  (no fan-out). More replicas spread the load.
- **FIFO per topic**, independent topics, payloads of any size (to several MB) and any Unicode.
- **`receive(topic, timeout)`** returns one message, or `None` after `timeout` seconds. The
  topic is chosen on every call, and messages published before the first `receive` must wait.
- **`publish`** returns once the server has accepted the message. Several threads may call
  it at the same time.
- **`from_url` does not connect.** Connect on first use, and reconnect once if the link drops.

Most queues fit directly (RabbitMQ, Redis lists, SQS, NATS JetStream work-queue streams,
Pulsar shared subscriptions). Log-based systems such as Kafka need care: one consumer group
for every replica, one partition per topic (or keyed messages) to keep FIFO,
`auto.offset.reset=earliest`, a commit after every message and a flush on every publish. Also,
joining a group can take longer than a 1 s `receive`. If the transport can't meet a rule, tell
the user before you start. Don't loosen the contract tests to make a backend pass.

Ask the user only about what you can't decide yourself, usually the client library. Prefer a
maintained **synchronous** client with type hints. The interface is sync, and the RabbitMQ
backend shows the pattern for a blocking client.

## 2. Scaffold

From the repo root. Try `--dry-run` first: it prints a diff of every change.

```bash
python3 .claude/skills/new-broker/scripts/scaffold.py <name> --title <Display Name> \
    --dependency "<client>>=<version>" \
    --image <server-image:tag> --port <client port> --healthcheck "<shell cmd, exit 0 when ready>"
```

| Option | Meaning |
| --- | --- |
| `<name>` | lowercase id, e.g. `nats`. Used as the extra, compose service and profile, and `brokers/<name>.env` |
| `--scheme` | URL scheme, repeatable (`--scheme nats --scheme tls`). Default: `<name>` |
| `--title`, `--class`, `--module` | display name, class (default `<Title>Broker`), module under `messaging/backends/` (default `<name>`) |
| `--dependency` | client-library requirement. Leave it out for a stdlib-only transport (then no extras are added) |
| `--client-import` + `--untyped` | add a mypy `ignore_missing_imports` override for a client without type hints |
| `--image`, `--port`, `--healthcheck`, `--container-env K=V` | the server for compose and the CI service container |
| `--compose-url`, `--test-url`, `--test-env` | defaults: `<scheme>://<name>:<port>`, `<scheme>://localhost:<port>`, `MESSAGING_TEST_<NAME>_URL` |

It refuses to run if the scheme, extra, module, compose service or test file name already
exists. It writes:

| File | Change |
| --- | --- |
| `packages/messaging/src/messaging/backends/<module>.py` | a `Broker` subclass with `from_url`; `publish`/`receive` raise `NotImplementedError` |
| `packages/messaging/tests/test_<module>.py` | scheme → class registry test, plus a test against a real server (skipped unless `--test-env` is set) |
| `packages/messaging/src/messaging/broker.py` | `_BACKENDS` entries, `_EXTRAS` (for the "install the extra" hint), the docstring's URL list |
| `packages/messaging/pyproject.toml` | the `<name>` extra |
| `packages/messaging/tests/conftest.py` | a `REAL_BROKERS` entry, so every contract test also runs against a real server when the URL is set |
| root `pyproject.toml` | the client in the `dev` group (so everything is testable locally), and the mypy override if `--untyped` |
| `apps/*` that carry broker extras | a `<name> = ["messaging[<name>]"]` extra, plus `<name>` added to `ARG BROKER_EXTRAS` in their Dockerfile |
| `compose.yaml` | `BROKER_EXTRAS` defaults, a `profiles: [<name>]` server, and the `x-broker-depends` anchor |
| `brokers/<name>.env` | `COMPOSE_PROFILES` + `BROKER_URL`, for `docker compose --env-file brokers/<name>.env up` |
| `.github/workflows/ci.yml` | service container + `MESSAGING_TEST_*` URL in the `brokers` job, `<name>` in the `compose` matrix |

New services pick the extra up automatically: the new-service scaffold reads the extras
from `packages/messaging/pyproject.toml`.

### Without `--image`

The script then leaves compose and CI alone, and writes `brokers/<name>.env` only if you
pass `--compose-url`. Wire them by hand:

- **A server you write yourself** (like `apps/tcp-broker`): create it with the new-service
  skill, then add a `profiles: [<name>]` compose service that builds it, like `tcp-broker`.
  Add a `HEALTHCHECK` and a `x-broker-depends` entry, plus `<name>` to the CI compose matrix.
  If it can run in-process, add an always-on param to `any_broker` (see `"tcp"` in `conftest.py`).
- **A managed cloud service** (e.g. SQS): use an emulator image for compose and CI if one
  exists (e.g. LocalStack), and pass it as `--image`. Otherwise say plainly that only the
  unit tests run.

## 3. Implement the backend

Read `backends/rabbitmq.py` (blocking client: lazy connection, one lock, reconnect and retry
once) and `backends/redis_broker.py` (client that is already thread-safe) first, and follow
their structure:

- Map topics 1:1 onto the transport's queue concept, and create them on first use (idempotently).
- Keep the delivery guarantee the others have (at-most-once: ack/remove as soon as it is
  received), or document a stronger one in the module docstring. Fill in the docstring's TODOs.
- `receive` must return within about `timeout`. If the client has no blocking get with a
  timeout, poll with a short sleep, as RabbitMQ does with `process_data_events`.
- Hold a lock around a connection that isn't thread-safe. `close()` must be idempotent.
- If the client is asyncio-only, run one event loop on a daemon thread and submit work to it
  with `asyncio.run_coroutine_threadsafe(...).result(timeout)`. Don't call `asyncio.run` per call.
- Let a constructor argument take a fake connection or client (as `RabbitMQBroker` takes a
  `connection_factory`), so the logic is unit-testable without a server.
- `third-party deps`: only through the extra. The core of `messaging` stays dependency-free
  (just pydantic).

## 4. Tests

- **Contract**: the `REAL_BROKERS` entry runs all of `test_messaging.py` against a real server
  when `MESSAGING_TEST_<NAME>_URL` is set. If an in-process fake of the server exists (like
  `fakeredis`), add it as an always-on param of `any_broker` so the contract also runs without one.
- **Backend-specific** (`tests/test_<module>.py`): keep the registry and "messages wait for a
  later consumer" tests, and add tests for reconnecting after a dropped connection, for the
  URL parsing (credentials, TLS scheme, defaults), and for a missing host, as
  `test_rabbitmq.py` and `test_registry.py` do. Annotate everything (mypy strict).
- Test file names must be unique across the repo (mypy reports duplicate modules).

## 5. Verify (all must pass before you report done)

```bash
uv lock && uv sync --all-packages      # the new client library; commit uv.lock
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest packages/messaging apps
uv lock --check
```

If Docker is available, run the real-server tests and the end-to-end smoke test too:

```bash
docker run -d --rm --name <name>-test -p <port>:<port> <image>
MESSAGING_TEST_<NAME>_URL=<test-url> uv run pytest packages/messaging
docker stop <name>-test
scripts/ci/compose_smoke.sh <name>     # an order travels orders-api -> <name> -> notifier-worker
```

If Docker isn't available, say so. Don't claim the backend works against a real server
without having run it there. Unit tests alone don't show that.

## 6. Update the docs

- `ARCHITECTURE.md` "Pluggable transport": the `classDiagram` (class + `Broker <|--` edge),
  the `broker_from_url()` flowchart, the backend table (URL, delivery, survives a broker
  restart, needs), and the "known schemes" line in the error example.
- `README.md`: the summary line and the "Use a different message broker" row, the
  `messaging/` comment in **Layout**, and the env-file list under **Running it**.
- The comments that list the brokers: `packages/messaging/pyproject.toml` `description`,
  the compose.yaml header, the `BROKER_EXTRAS` comments in the app Dockerfiles, and the
  `brokers` job comment in `ci.yml`.

## 7. Wrap up

Commit everything together: the backend and its tests, `broker.py`, the pyprojects,
`uv.lock`, Dockerfiles, `compose.yaml`, `brokers/<name>.env`, `ci.yml` and the docs. Then
summarise for the user:

- the URL scheme(s) and an example `BROKER_URL`
- the delivery guarantee
- how to run the stack on the new broker: `docker compose --env-file brokers/<name>.env up --build`
- which checks ran, and which (real server, compose) could not
