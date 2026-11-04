# python-monorepo

A Python monorepo managed as a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/).
All members share one virtualenv and one `uv.lock`.

## What this project is

A working template for building **several Python services and libraries in one repository**
while still testing, building and deploying each one on its own. It ships a small but
realistic microservice system so you can see every piece working together:

- **`catalog-api`** lists products, **`orders-api`** places orders (calling the catalog over
  HTTP) and publishes an `order.placed` event, and **`notifier-worker`** consumes that event
  and sends a notification.
- The services share code only through libraries in `packages/`: typed **contracts**
  (pydantic models for API payloads and events), a pluggable **messaging** layer (Redis,
  RabbitMQ, a built-in TCP broker or in-memory, chosen with one `BROKER_URL`) and
  **servicekit** (settings, logging, a FastAPI app factory with `/health`).
- The tooling around them is already wired up: strict `mypy`, `ruff`, `pytest`, pre-commit,
  one slim Docker image per app, a `compose.yaml` for running everything locally, and CI
  that **only tests what your change affects**.

The example domain (products, orders, notifications) is deliberately small. The point is the
structure, which you keep, and the examples, which you replace or grow.

## Using it for your needs

Pick the path that matches what you want to do:

| You want to... | Do this |
| --- | --- |
| **Try it out / learn the pattern** | Follow [Getting started](#getting-started), run the stack with `docker compose up --build`, and read [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams of how the pieces fit. |
| **Start your own project from it** | Fork or copy the repo, delete the example apps you don't need (and their entries in `compose.yaml` and the root `pyproject.toml` ruff/mypy lists), then add your own services. Keep `packages/servicekit` and `packages/messaging`; they're domain-agnostic. |
| **Add a new HTTP API or worker** | Scaffold one that is fully wired in (package, Dockerfile, compose, lint/type config, tests): `python3 .claude/skills/new-service/scripts/scaffold.py inventory-api --kind http` (or `--kind worker --event ... --topic ...`). With Claude Code, just ask it to "add a new service"; the bundled `new-service` skill does the whole job. See [Adding a new service](ARCHITECTURE.md#adding-a-new-service). |
| **Add a shared library** | Create it under `packages/` and depend on it from your apps; see [Adding a member](#adding-a-member). |
| **Share data between services** | Put request/response models and events in `packages/contracts`, so producer and consumer use the same typed definition. |
| **Use a different message broker** | Switch between Redis, RabbitMQ and TCP with an env file (see below), or add a new backend (Kafka, NATS, SQS, ...) by implementing the `Broker` interface; see [ARCHITECTURE.md](ARCHITECTURE.md#adding-another-broker-kafka-nats-sqs-). |
| **Deploy services separately** | Build each app's image on its own and version/scale it independently; see [Deploying services independently](#deploying-services-independently). |
| **Keep CI fast as the repo grows** | Nothing to do: CI works out which members a change affects from the `pyproject.toml` files. See [CI](#ci). |

![Demo: services talking over HTTP and Redis, CI testing only affected members, and scaffolding a new service](docs/demo.gif)

<sub>Real commands and output, replayed by [`docs/demo/player.html`](docs/demo/player.html). Also available as an [MP4](docs/demo.mp4). Regenerate with `node docs/demo/record.mjs`.</sub>

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for diagrams of the layout, dependency graph,
runtime flow, CI and deployment.

## Layout

```
.
├── pyproject.toml          # workspace root (virtual, not published) + ruff/mypy/pytest config
├── uv.lock                 # single lockfile for the whole workspace
├── compose.yaml            # run all services together locally (one profile per broker)
├── .env, brokers/*.env     # which broker compose starts and BROKER_URL points at
├── packages/               # reusable libraries
│   ├── contracts/          # shared pydantic models: API payloads + events
│   ├── messaging/          # Broker interface + Redis / RabbitMQ / TCP / in-memory backends
│   ├── servicekit/         # settings, logging, FastAPI app factory with /health
│   └── core/               # tiny greeting helper used by apps/cli
└── apps/                   # deployables, each with its own Dockerfile
    ├── catalog-api/        # HTTP: product catalog
    ├── orders-api/         # HTTP: places orders, calls catalog-api, publishes events
    ├── notifier-worker/    # worker: consumes order events, sends notifications
    ├── tcp-broker/         # optional dependency-free broker server for tcp:// URLs
    └── cli/                # command-line example
```

Every member has the same shape: `pyproject.toml`, `src/<import_name>/`, `tests/`.

## Getting started

```bash
uv sync --all-packages        # create .venv with every member + dev tools
uv run pre-commit install     # enable git hooks
uv run cli Ada                # -> Hello, Ada!
```

Run the example services together (needs Docker):

```bash
docker compose up --build
curl localhost:8001/products
curl -X POST localhost:8002/orders -H 'content-type: application/json' \
     -d '{"customer_email":"ada@example.com","items":[{"sku":"MUG-001","quantity":2}]}'
docker compose logs notifier-worker   # -> "notify to=ada@example.com ..."
```

The services don't care which message broker carries their events; `BROKER_URL` decides.
Redis is the default. To run the same stack on another broker, pick its env file:

```bash
docker compose --env-file brokers/rabbitmq.env up --build   # RabbitMQ
docker compose --env-file brokers/tcp.env up --build        # built-in TCP broker
docker compose --profile "*" down                           # stop, whichever is running
```

See [ARCHITECTURE.md](ARCHITECTURE.md#messaging-a-pluggable-transport) for how the transport
is plugged in and how to add another one.

## Everyday commands

```bash
uv run ruff check .           # lint
uv run ruff format .          # format
uv run mypy                   # type-check (strict)
uv run pytest                 # run all tests
uv run pytest packages/core   # test one member
uv run pre-commit run --all-files
```

## Adding a member

1. Create `packages/<name>/` (library) or `apps/<name>/` (deployable) with a
   `pyproject.toml` and `src/<name>/` layout. `uv init --lib packages/<name>` works too.
2. Depend on another member by listing it in `dependencies` **and** marking it as a
   workspace source:

   ```toml
   [project]
   dependencies = ["core"]

   [tool.uv.sources]
   core = { workspace = true }
   ```

3. Add its `src` dir to `mypy_path` and its import name to ruff's `known-first-party`
   in the root `pyproject.toml`.
4. Run `uv sync --all-packages` and commit the updated `uv.lock`.

Third-party dependencies go in the member that uses them (`uv add --package <name> <dep>`);
shared dev tooling lives in the root `dev` dependency group.

## Deploying services independently

Each app under `apps/` is its own deployable with its own `Dockerfile`, built from the
repo root so the shared lockfile is used but **only that app and the workspace packages it
depends on** are installed (no dev tools, no other apps):

```bash
docker build -f apps/orders-api/Dockerfile -t orders-api .
docker build -f apps/cli/Dockerfile -t cli .
docker run --rm cli Ada
```

Because every app gets its own image, each one can be versioned, released and scaled
(replicas, autoscaling, resources) on its own. A change to `packages/core` only needs to
rebuild the apps that depend on it. To add a service, copy the closest example app (see
[ARCHITECTURE.md](ARCHITECTURE.md#adding-a-new-service)).

## CI

`.github/workflows/ci.yml` runs on every pull request and on pushes to `main`:

- **Lint and type check**: `ruff check`, `ruff format --check` and `mypy` over the whole repo.
- **Tests**: `pytest` runs only for the members that changed **plus every member that
  depends on them**, one matrix job per member. `scripts/ci/affected.py` works this out
  from the workspace `pyproject.toml` files, so there is nothing extra to maintain when you
  add a member. A change to a shared file outside any member (root `pyproject.toml`,
  `uv.lock`, the workflow itself, ...) runs every member; Markdown and `docs/` changes run none.
- **Brokers / end-to-end**: when `packages/messaging` or a service using it changes, the
  messaging tests also run against real Redis and RabbitMQ, and the compose stack is started
  once per broker (`scripts/ci/compose_smoke.sh`) to send a real order through it.
- **CI OK**: a single summary job to mark as required in branch protection; it passes when
  test jobs are skipped because nothing relevant changed.

uv's cache is keyed on `uv.lock`, and `UV_LOCKED=1` fails the build if the lockfile is out
of date. To see what CI would test for your branch:

```bash
python3 scripts/ci/affected.py --base origin/main
```
