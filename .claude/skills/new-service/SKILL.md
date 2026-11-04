---
name: new-service
description: Create a new deployable service in this monorepo (an HTTP API or a background worker under apps/), fully wired in - package, Dockerfile, shared contracts, root pyproject ruff/mypy config, compose.yaml, tests and docs - and verified with ruff, mypy and pytest. Use when the user asks to add, create, scaffold or bootstrap a new service, API, microservice, worker or consumer.
---

# Create a new service

Every service in `apps/` has the same shape and the same wiring (see `ARCHITECTURE.md`).
This skill makes a new one complete and consistent: a scaffold script handles the
mechanical parts, and you write the domain logic, tests and docs.

## 1. Pin down the design (ask only what you can't infer)

Get these from the request; ask the user only about items that are genuinely unclear:

- **Name**: kebab-case. HTTP services end in `-api`, workers end in `-worker`. The import
  name is the name with `_` instead of `-` (`inventory-api` becomes `inventory_api`).
- **Kind**: `http` (FastAPI, serves requests) or `worker` (consumes broker events).
- **Responsibility**: what it owns, in one sentence. That sentence becomes the description.
- **Interactions**:
  - Calls another service over HTTP? Write a client like `apps/orders-api/src/orders_api/catalog_client.py`
    (a Protocol port plus an `httpx` implementation), and add a `<OTHER>_URL` setting.
  - Publishes events? HTTP: use `--broker`. Event models go in `packages/contracts`.
  - Consumes events? Use kind `worker` with `--event` and `--topic`.
- **Endpoints / events**: routes and payloads, or the event and what to do with it.

Never import another app. Services share only `packages/` libraries, and talk over HTTP or the broker.

## 2. Contracts first (if any data crosses a service boundary)

Request/response bodies that other services use, and every event, belong in
`packages/contracts/src/contracts/`. Follow the existing style: pydantic `BaseModel`, `frozen=True`
for values and events, integer cents for money, `Field` constraints. Name topics
`<noun>.<past-verb>` (e.g. `stock.reserved`) as an `UPPER_SNAKE_TOPIC` constant next to the
event. Export everything from `contracts/__init__.py` (`__all__` is sorted), and add a test in
`packages/contracts/tests/`. A worker scaffold checks that `--event`/`--topic` are exported.

Models used only inside the service stay inside the service.

## 3. Scaffold

From the repo root (try `--dry-run` first if you want a preview):

```bash
# HTTP service (add --broker if it publishes events; --host-port N to choose the compose port)
python3 .claude/skills/new-service/scripts/scaffold.py <name> --kind http --description "..."

# Worker consuming an event from contracts
python3 .claude/skills/new-service/scripts/scaffold.py <name> --kind worker \
    --event <EventModel> --topic <TOPIC_CONSTANT> --description "..."
```

The script refuses invalid names, existing members and unknown contracts. It writes:

| File | Purpose |
| --- | --- |
| `apps/<name>/pyproject.toml` | workspace deps (`contracts`, `servicekit[http]` or plain `servicekit`, `messaging` if needed) + console script |
| `apps/<name>/Dockerfile` | the repo's two-stage uv build; HTTP adds `EXPOSE 8000` and a `/health` `HEALTHCHECK` |
| `src/<pkg>/main.py` | entry point: settings, logging, serve/run (workers handle SIGTERM) |
| `src/<pkg>/app.py` + `service.py` (http) | thin FastAPI routes over a pure service class |
| `src/<pkg>/worker.py` (worker) | `handle` / `process_one` / `run` consume loop |
| `tests/test_<pkg>.py` | starter tests (health check / consume loop) |
| root `pyproject.toml` | adds the import name to ruff `known-first-party` and `apps/<name>/src` to `mypy_path` |
| `compose.yaml` | service entry; host port = highest app port (`"N:8000"`) + 1; broker services get the shared `*broker-env` / `*broker-depends` anchors, so they follow whichever broker is selected |
| `pyproject.toml` + `Dockerfile` (broker services) | one extra per broker client (read from `packages/messaging/pyproject.toml`) and the `BROKER_EXTRAS` build arg, so images can carry any broker client |

CI (`scripts/ci/affected.py`) and the workspace glob pick up the new member automatically.
Nothing to edit there.

## 4. Implement it the way the existing services are written

Read the closest example before you write code: `apps/catalog-api` (simple HTTP),
`apps/orders-api` (HTTP that calls another service and publishes), and `apps/notifier-worker` (worker).

- **Layering**: `main.py` wires the process. `app.py` holds routes only: validate, call the
  service, map domain exceptions to `HTTPException` (404 not found, 422 invalid domain input).
  `service.py` (or `worker.py`'s `handle`) holds pure logic with no FastAPI and no network.
- **Ports**: anything external (another service, broker, store, email provider) goes behind a
  `typing.Protocol`, gets injected through the constructor, and gets a fake for tests.
  `build_app(settings, service)` takes optional overrides, so tests never touch the network.
- **Storage**: an in-memory repository class (like `catalog_api/repository.py`) unless the
  user asks for a database. If they do, keep the same repository interface.
- **Settings**: subclass `servicekit.ServiceSettings`, with one field per env var and safe local
  defaults (`memory://` broker for HTTP services, `http://localhost:<port>` for upstream URLs).
- **Third-party deps**: `uv add --package <name> <dep>` (e.g. `httpx`). Never add them to the root.
- **Workers**: replace the placeholder `handle`. Keep the loop resilient: one bad message
  must not kill it. Put logic that is worth testing in pure functions (see `render` in notifier-worker).
- **Typing**: mypy runs in strict mode. Annotate everything, including tests.
- Delete the scaffold's placeholder comments once real routes exist. `app.state.service`
  can go if the routes close over `service` directly.

## 5. Tests

Cover real behaviour, not just the scaffold:

- HTTP: every route's happy path, plus its 404/422 paths, through `TestClient(build_app(service=...))`
  with fakes. If it publishes, assert the event with `InMemoryBroker` + `receive_event`. Test
  HTTP clients with `httpx.MockTransport` (see `apps/orders-api/tests`).
- Worker: build a real event from contracts, `publish_event` it to an `InMemoryBroker`, and
  assert `process_one(broker, handler=recorder)` handles it. Keep the malformed-message test.
- Test file names must be unique across the repo (mypy reports duplicate modules), which is why
  they are named `test_<pkg>.py`.

## 6. Verify (all must pass before you report done)

```bash
uv sync --all-packages                 # also updates uv.lock; commit it
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest apps/<name> packages/contracts   # plus any service whose contracts you changed
uv lock --check
python3 scripts/ci/affected.py --base origin/main   # confirm CI will test what you expect
```

If Docker is available, also run `docker build -f apps/<name>/Dockerfile -t <name> .`, and for
HTTP services run `docker compose up --build <name>` and then `curl localhost:<port>/health`. If
Docker is not available, say so; don't claim the image was tested.

## 7. Update the docs

`ARCHITECTURE.md` is the system map, so keep it accurate:

- the members table at the top
- the **Dependency graph** mermaid (node + edges) and the "If you change..." CI table rows
  for every library the service depends on
- the **Runtime** sequence diagram, if the service joins an existing flow
- the image contents table under **Container build**
- the **Deployment** diagram and the env var table (every new setting)

In `README.md`, add the app to the **Layout** tree, and add a curl example if it is user-facing.

## 8. Wrap up

Commit everything together: `apps/<name>/`, root `pyproject.toml`, `uv.lock`, `compose.yaml`,
any `packages/contracts` changes, and the docs. Then summarise for the user: the endpoints or
events, the env vars, the compose port, and which checks ran (and which, like Docker, could not).
