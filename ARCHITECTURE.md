# Architecture

This repository is a **Python monorepo**: many independently deployable services and the
libraries they share live in one Git repository, managed as a single
[uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with one lockfile.

The example system is a tiny shop:

| Member | Kind | What it does |
| --- | --- | --- |
| `apps/catalog-api` | HTTP service | Owns the product list and prices. |
| `apps/orders-api` | HTTP service | Accepts orders, prices them by calling `catalog-api`, publishes an `OrderPlaced` event. |
| `apps/notifier-worker` | Background worker | Consumes `OrderPlaced` events and sends a confirmation to the customer. |
| `apps/tcp-broker` | Broker server | Optional, dependency-free message broker for `tcp://` URLs. |
| `apps/cli` | Command-line app | The original "hello" example. |
| `packages/contracts` | Library | Shared pydantic models: API payloads (`Product`, `Order`, ...) and events (`OrderPlaced`). |
| `packages/messaging` | Library | Transport-neutral `Broker` interface, backends for Redis, RabbitMQ, TCP and in-memory picked by `BROKER_URL`, plus typed `publish_event` / `receive_event`. |
| `packages/servicekit` | Library | Settings from env vars, uniform logging, and (with the `http` extra) a FastAPI app factory with `/health`. |
| `packages/core` | Library | The original greeting helper used by `apps/cli`. |

## Principles

1. **`packages/` are libraries, `apps/` are deployables.** Libraries are imported; apps are
   run. An app never imports another app.
2. **Services talk over the network, not through imports.** `orders-api` calls `catalog-api`
   over HTTP and reaches `notifier-worker` through the message broker. What they share is the
   *shape* of the data, in `packages/contracts`.
3. **Infrastructure is a plug, not a dependency.** Services code against the `Broker`
   interface only. Which broker carries the messages (Redis, RabbitMQ, TCP, ...) is
   configuration (`BROKER_URL`), so swapping it needs no code change.
4. **One lockfile, one version of each dependency.** Every member resolves against the same
   `uv.lock`, so there is no "works with my version" drift between services.
5. **Each app ships alone.** Every app has its own `Dockerfile` that installs only that app and
   the libraries it depends on, so each one is built, released and scaled on its own.
6. **CI tests what a change can break.** A change to a library re-tests the library and every
   app that depends on it; untouched members are skipped.

## Repository layout

```mermaid
flowchart LR
    root(["python-monorepo/"])

    root --> rootfiles["pyproject.toml<br/>(workspace + ruff/mypy/pytest config)<br/>uv.lock · compose.yaml · .env"]
    root --> brokers["brokers/<br/>redis.env · rabbitmq.env · tcp.env"]
    root --> ci[".github/workflows/ci.yml<br/>scripts/ci/affected.py<br/>scripts/ci/compose_smoke.sh"]
    root --> tooling[".claude/skills/<br/>new-service · new-broker<br/>(scaffold a wired-in service or backend)"]
    root --> docs["docs/<br/>demo.gif · brokers.gif (+ .mp4)<br/>demo/player.html · demo/record.mjs"]
    root --> pkgs["packages/ (libraries)"]
    root --> apps["apps/ (deployables)"]

    pkgs --> contracts["contracts/"]
    pkgs --> messaging["messaging/"]
    pkgs --> servicekit["servicekit/"]
    pkgs --> core["core/"]

    apps --> catalog["catalog-api/"]
    apps --> orders["orders-api/"]
    apps --> notifier["notifier-worker/"]
    apps --> tcpb["tcp-broker/"]
    apps --> cli["cli/"]

    orders --> member["Every member has the same shape:<br/>pyproject.toml<br/>src/&lt;import_name&gt;/<br/>tests/<br/>Dockerfile (apps only)"]
```

## Dependency graph

Arrows point from a member to what it depends on. This is the graph CI walks (in reverse) to
decide what to test.

```mermaid
flowchart TB
    subgraph apps["apps/ · deployables"]
        catalog["catalog-api"]
        orders["orders-api"]
        notifier["notifier-worker"]
        tcpb["tcp-broker"]
        cli["cli"]
    end

    subgraph packages["packages/ · shared libraries"]
        contracts["contracts"]
        messaging["messaging"]
        servicekit["servicekit"]
        core["core"]
    end

    subgraph thirdparty["third-party (pinned in uv.lock)"]
        pydantic(["pydantic"])
        settings(["pydantic-settings"])
        fastapi(["fastapi + uvicorn"])
        redis(["redis"])
        pika(["pika"])
        httpx(["httpx"])
    end

    catalog --> contracts
    catalog -- "servicekit[http]" --> servicekit
    orders --> contracts
    orders --> messaging
    orders -- "servicekit[http]" --> servicekit
    orders --> httpx
    notifier --> contracts
    notifier --> messaging
    notifier --> servicekit
    tcpb --> messaging
    tcpb --> servicekit
    cli --> core

    contracts --> pydantic
    messaging --> pydantic
    messaging -. "redis extra" .-> redis
    messaging -. "rabbitmq extra" .-> pika
    servicekit --> settings
    servicekit -. "http extra only" .-> fastapi
```

`notifier-worker` depends on plain `servicekit` (without the `http` extra), so FastAPI and
uvicorn never end up in its image. In the same way, `messaging` itself needs only pydantic:
the Redis and RabbitMQ client libraries are extras (`messaging[redis]`, `messaging[rabbitmq]`)
that each app re-exports as its own `redis` / `rabbitmq` extras, and the Dockerfile decides
which ones go into the image. `tcp-broker` uses neither.

| If you change... | CI tests... |
| --- | --- |
| `packages/contracts` | contracts, catalog-api, orders-api, notifier-worker |
| `packages/messaging` | messaging, orders-api, notifier-worker, tcp-broker (+ broker integration and end-to-end jobs) |
| `packages/servicekit` | servicekit, catalog-api, orders-api, notifier-worker, tcp-broker |
| `packages/core` | core, cli |
| `apps/orders-api` | orders-api only |
| root `pyproject.toml`, `uv.lock`, CI files, `compose.yaml` | everything |
| `*.md`, `docs/` | nothing (lint still runs) |

## Runtime: how the services interact

```mermaid
sequenceDiagram
    autonumber
    actor Customer
    participant Orders as orders-api
    participant Catalog as catalog-api
    participant Broker as Broker (Redis / RabbitMQ / TCP)
    participant Notifier as notifier-worker

    Customer->>Orders: POST /orders {customer_email, items}
    loop for each item
        Orders->>Catalog: GET /products/{sku}
        Catalog-->>Orders: Product {sku, name, price_cents}
    end
    alt any SKU unknown
        Orders-->>Customer: 422 unknown product
    else all SKUs found
        Orders->>Orders: compute total, store Order
        Orders->>Broker: publish("orders.placed", OrderPlaced JSON)
        Orders-->>Customer: 201 Order
        Notifier->>Broker: receive("orders.placed", timeout=1s)
        Broker-->>Notifier: OrderPlaced
        Notifier->>Notifier: render message and send it
    end
```

The broker is a work queue: each event goes to exactly one worker replica, so running more
`notifier-worker` replicas spreads the load rather than sending duplicate notifications. Every
backend keeps that promise, so the flow above is identical whichever broker is configured.

```mermaid
flowchart LR
    orders["orders-api<br/>(any number of replicas)"] -->|"publish OrderPlaced #1 #2 #3 #4"| q[("orders.placed queue<br/>Redis list · RabbitMQ queue · tcp-broker FIFO")]
    q -->|"#1, #3"| w1["notifier-worker replica 1"]
    q -->|"#2, #4"| w2["notifier-worker replica 2"]
```

This is a real run (two replicas on the TCP broker, four orders), from
[`docs/brokers.mp4`](docs/brokers.mp4): replica 1 notified ada and alan, replica 2 grace and
linus, and nobody was notified twice.

## Messaging: a pluggable transport

![Demo: the same services on Redis, then on the TCP broker, two worker replicas sharing a queue, and the contract tests](docs/brokers.gif)

<sub>Real commands and output (also as an [MP4](docs/brokers.mp4)). Regenerate with `node docs/demo/record.mjs brokers`.</sub>

`packages/messaging` separates *what* a service does with messages from *how* they travel.
Services see one abstract class, `Broker`, with `publish(topic, message)`,
`receive(topic, timeout)` and `close()`. Each backend implements it on top of one technology:

```mermaid
classDiagram
    direction LR
    class Broker {
        <<abstract>>
        +publish(topic, message)
        +receive(topic, timeout) str | None
        +close()
    }
    class InMemoryBroker {
        memory://
        process-local, for tests
    }
    class RedisBroker {
        redis:// rediss://
        LPUSH / BRPOP on a list
    }
    class RabbitMQBroker {
        amqp:// amqps://
        durable queue, persistent messages
    }
    class TcpBroker {
        tcp://host:port
        JSON lines to apps/tcp-broker
    }
    Broker <|-- InMemoryBroker
    Broker <|-- RedisBroker
    Broker <|-- RabbitMQBroker
    Broker <|-- TcpBroker
```

`broker_from_url(settings.broker_url)` reads the URL scheme and builds the matching backend.
Backends are imported lazily, so an image that left out the RabbitMQ client still starts with
`redis://` (and fails with a clear "install the `rabbitmq` extra" error if pointed at `amqp://`).

```mermaid
flowchart LR
    env["BROKER_URL env var"] --> settings["Settings.broker_url"]
    settings --> factory{"broker_from_url()<br/>looks at the scheme"}
    factory -- "memory://" --> mem["InMemoryBroker"]
    factory -- "redis://" --> red["RedisBroker"] --> r[("Redis")]
    factory -- "amqp://" --> rab["RabbitMQBroker"] --> q[("RabbitMQ")]
    factory -- "tcp://" --> tcp["TcpBroker"] --> t[("apps/tcp-broker")]
    factory -- "anything registered" --> custom["your backend"]
    mem & red & rab & tcp & custom --> iface[["Broker interface"]]
    iface --> svc["OrderService / worker loop<br/>(unchanged)"]
```

| Backend | URL | Delivery | Survives broker restart | Needs |
| --- | --- | --- | --- | --- |
| In-memory | `memory://` | one process only | no | nothing (tests) |
| Redis | `redis://host:6379/0` | each message to one consumer | if Redis persistence is on | `redis` extra + a Redis server |
| RabbitMQ | `amqp://user:pass@host:5672/vhost` | each message to one consumer | yes (durable queue, persistent messages) | `rabbitmq` extra + a RabbitMQ server |
| TCP | `tcp://host:7000` | each message to one consumer | no (queues live in the server's memory) | the `tcp-broker` image, no client library |

Swapping is just a matter of where `BROKER_URL` points. Without Docker, using the
stdlib TCP broker (or `redis-server` and `redis://localhost:6379/0`):

```bash
uv run tcp-broker &
export BROKER_URL=tcp://localhost:7000
PORT=8001 uv run catalog-api &  PORT=8002 uv run orders-api &  uv run notifier-worker &
# the worker logs: listening on orders.placed via TcpBroker
```

An unknown scheme fails at start-up, not at the first message:
`BrokerError: unsupported broker URL 'kafka://localhost:9092'; known schemes: amqp, amqps, memory, redis, rediss, tcp`.

### The TCP broker

`apps/tcp-broker` is a small, standard-library-only server for `tcp://` URLs: no client library,
no external image. It keeps one FIFO queue per topic in memory and speaks one JSON object per
line in each direction:

```mermaid
sequenceDiagram
    participant P as orders-api<br/>(TcpBroker client)
    participant S as tcp-broker<br/>(TcpBrokerServer)
    participant C as notifier-worker<br/>(TcpBroker client)

    C->>S: {"op": "receive", "topic": "orders.placed", "timeout": 1.0}
    Note over S: queue empty: hold the request<br/>up to timeout (max 30 s)
    P->>S: {"op": "publish", "topic": "orders.placed", "message": "{...}"}
    S-->>P: {"ok": true}
    S-->>C: {"ok": true, "message": "{...}"}
    Note over S,C: if the reply can't be written (client gone),<br/>the message goes back to the front of the queue
    C->>S: {"op": "receive", ...}
    S-->>C: {"ok": true, "message": null} after the timeout
    Note over S: {"op": "ping"} → {"ok": true} is the Docker HEALTHCHECK<br/>(tcp-broker --check). Errors → {"ok": false, "error": "..."}
```

Clients hold one connection, are thread-safe and reconnect once if the link drops. Because
queues live in the server's memory, messages are lost if it restarts; use Redis or RabbitMQ
where that matters.

All four pass the same contract tests (`packages/messaging/tests/test_messaging.py`): FIFO
order, timeouts, independent topics, large and non-ASCII payloads, and concurrent publishers.

### Adding another broker (Kafka, NATS, SQS, ...)

With Claude Code, ask it to add the broker: the `new-broker` skill (`.claude/skills/new-broker/`)
checks that the transport fits the contract, does every step below and verifies the result. The
wiring alone is one command (`--dry-run` prints the diff first):

```bash
python3 .claude/skills/new-broker/scripts/scaffold.py nats --title NATS --dependency "nats-py>=2.9" \
    --image nats:2-alpine --port 4222 --healthcheck "wget -q -O- localhost:8222/healthz"
```

It leaves you the `publish`/`receive` logic, the backend's own tests and the docs. By hand:

1. Add `packages/messaging/src/messaging/backends/<name>.py` with a `Broker` subclass and a
   `from_url(cls, url)` classmethod.
2. Map its URL scheme in `_BACKENDS` in `messaging/broker.py` (or call
   `register_backend("nats", NatsBroker.from_url)` from your own code), and add the client
   library as a new extra in `packages/messaging/pyproject.toml` and the apps' extras.
3. Add it to `REAL_BROKERS` (or, for an in-process fake, the `any_broker` params) in
   `packages/messaging/tests/conftest.py`, so the contract tests run against it.
4. Add a service with a `profiles: [<name>]` entry to `compose.yaml` and a
   `brokers/<name>.env`, and add it to the `compose` matrix in CI.

No service code changes.

### Inside a service

Each app keeps business logic apart from transport so it can be tested without a network:

```mermaid
flowchart LR
    subgraph orders-api
        main["main.py<br/>read Settings, configure logging, serve"] --> app["app.py<br/>FastAPI routes"]
        app --> service["service.py<br/>OrderService (pure logic)"]
        service --> port1[["Catalog protocol"]]
        service --> port2[["Broker protocol"]]
    end
    port1 -- production --> http["HttpCatalog (httpx)"]
    port1 -. tests .-> fake["FakeCatalog"]
    port2 -- "BROKER_URL=redis://" --> rb["RedisBroker"]
    port2 -- "BROKER_URL=amqp://" --> qb["RabbitMQBroker"]
    port2 -- "BROKER_URL=tcp://" --> tb["TcpBroker"]
    port2 -. tests .-> mb["InMemoryBroker"]
```

## Build and CI flow

```mermaid
flowchart TD
    dev["Developer pushes a branch / opens a PR"] --> pre["pre-commit (local)<br/>ruff · mypy · uv lock --check"]
    pre --> gh["GitHub Actions: ci.yml"]

    gh --> changes["changes job<br/>scripts/ci/affected.py<br/>git diff base...HEAD → changed files<br/>→ owning members → + all dependents"]
    gh --> lint["lint job<br/>ruff check · ruff format --check · mypy (whole repo)"]

    changes -->|"matrix: affected members"| t1["test messaging"]
    changes --> t2["test orders-api"]
    changes --> t3["test notifier-worker"]
    changes --> t4["test tcp-broker"]
    changes -.->|"unaffected members skipped"| skip["(no job)"]
    changes -->|"messaging affected"| brk["brokers job<br/>contract tests vs real<br/>Redis + RabbitMQ services"]
    changes -->|"notifier-worker affected"| e2e["compose job · matrix<br/>redis · rabbitmq · tcp<br/>scripts/ci/compose_smoke.sh"]

    t1 & t2 & t3 & t4 --> ok{"CI OK<br/>(required check)"}
    brk & e2e --> ok
    lint --> ok
    ok -->|"all success / skipped"| merge["PR can be merged into main"]
    ok -->|"any failure"| fix["Fix and push again"]
```

The matrix shown is what a change to `packages/messaging` produces: messaging plus its three
dependents, while catalog-api, cli and the other libraries are skipped. Two more jobs guard the transport: **brokers** runs the messaging
contract tests against real Redis and RabbitMQ containers, and **compose** builds the real
images and sends an order from `orders-api` to `notifier-worker` over each broker in turn. The
unit test job already covers the in-memory, fakeredis and TCP backends. To see what CI would
test for your branch, run `python3 scripts/ci/affected.py --base origin/main`.

## Container build

Every app's `Dockerfile` follows the same two-stage pattern and is built **from the repo root**
so it can see `uv.lock` and the shared libraries:

```mermaid
flowchart LR
    subgraph ctx["Build context: repo root"]
        lock["uv.lock + pyproject.toml"]
        src["packages/ + apps/"]
    end

    subgraph builder["Stage 1: builder (uv image)"]
        s1["uv sync --no-install-workspace --package APP --extra ...<br/>third-party deps only<br/>(cached until uv.lock changes)"]
        s2["uv sync --no-editable --package APP --extra ...<br/>APP + only the libraries it needs"]
        s1 --> s2
    end

    subgraph runtime["Stage 2: runtime (python slim)"]
        venv["/app/.venv<br/>non-root user<br/>ENTRYPOINT = APP"]
    end

    arg["build arg BROKER_EXTRAS<br/>default: redis rabbitmq"] -.-> s1 & s2
    lock --> s1
    src --> s2
    s2 -->|"copy .venv only"| venv
```

What actually lands in each image:

| Image | Workspace libraries | Notable third-party |
| --- | --- | --- |
| `catalog-api` | contracts, servicekit | fastapi, uvicorn |
| `orders-api` | contracts, messaging, servicekit | fastapi, uvicorn, httpx, + broker clients from `BROKER_EXTRAS` |
| `notifier-worker` | contracts, messaging, servicekit | broker clients from `BROKER_EXTRAS` (no web server) |
| `tcp-broker` | messaging, servicekit | none |
| `cli` | core | none |

```bash
docker build -f apps/orders-api/Dockerfile -t orders-api .            # redis + pika inside
docker build --build-arg BROKER_EXTRAS=rabbitmq \
    -f apps/orders-api/Dockerfile -t orders-api:rabbitmq .             # pika only
```

By default `BROKER_EXTRAS="redis rabbitmq"`, so one image can be pointed at any broker by
changing `BROKER_URL` at deploy time. Narrow it if you want the smallest image for the
broker you actually run; `tcp://` and `memory://` need no extra at all.

## Deployment

Each image is deployed and scaled on its own. The same topology runs locally with
`docker compose up --build` (see `compose.yaml`) and maps directly onto Kubernetes,
ECS, Cloud Run, etc.

```mermaid
flowchart LR
    users(["Clients"]) --> lb["Load balancer / ingress"]

    subgraph platform["Container platform"]
        subgraph cat["catalog-api (Deployment, N replicas)"]
            c1["pod"]
            c2["pod"]
        end
        subgraph ord["orders-api (Deployment, N replicas)"]
            o1["pod"]
            o2["pod"]
            o3["pod"]
        end
        subgraph wrk["notifier-worker (Deployment, scaled on queue length)"]
            w1["pod"]
            w2["pod"]
        end
        broker[("Message broker<br/>Redis, RabbitMQ or tcp-broker<br/>orders.placed queue")]
    end

    email(["Email / SMS provider"])

    lb -->|"/products"| cat
    lb -->|"/orders"| ord
    ord -->|"HTTP GET /products/{sku}<br/>CATALOG_URL"| cat
    ord -->|"publish<br/>BROKER_URL"| broker
    broker -->|"consume<br/>BROKER_URL"| wrk
    wrk --> email
```

Health checks: HTTP services expose `GET /health` (from `servicekit.http.create_app`) and their
images declare a Docker `HEALTHCHECK`, which `compose.yaml` uses to start `orders-api` only once
`catalog-api` is healthy. The worker shuts down cleanly on `SIGTERM`.

Configuration is by environment variable only (`servicekit.ServiceSettings`):

| Variable | Used by | Default |
| --- | --- | --- |
| `PORT`, `HOST` | HTTP services | `8000`, `0.0.0.0` |
| `LOG_LEVEL` | all | `INFO` |
| `ENVIRONMENT` | all (shown in `/health`) | `local` |
| `CATALOG_URL` | orders-api | `http://localhost:8001` |
| `BROKER_URL` | orders-api, notifier-worker | `memory://` (orders-api), `redis://localhost:6379/0` (worker). The scheme picks the backend: `redis://`, `amqp://`, `tcp://`, `memory://` |
| `PORT` | tcp-broker | `7000` |

### Choosing the broker with Docker Compose

Each broker is a Compose **profile**, and a small env file per broker sets two variables:
`COMPOSE_PROFILES` (which broker container to start) and `BROKER_URL` (where the services
connect). The app images and services stay the same.

```mermaid
flowchart LR
    subgraph files["env file you pick"]
        d[".env (default)<br/>= redis"]
        fr["brokers/rabbitmq.env"]
        ft["brokers/tcp.env"]
    end
    files --> compose["docker compose up --build"]
    compose -->|"COMPOSE_PROFILES"| start["starts one of:<br/>redis · rabbitmq · tcp-broker"]
    compose -->|"BROKER_URL"| apps["orders-api + notifier-worker<br/>(same images)"]
    apps -->|"depends_on, required: false<br/>waits for the one that is running"| start
```

```bash
docker compose up --build                                   # Redis (default, from .env)
docker compose --env-file brokers/rabbitmq.env up --build   # RabbitMQ (UI on :15672, guest/guest)
docker compose --env-file brokers/tcp.env up --build        # the stdlib TCP broker
docker compose --profile "*" down                           # stop, whichever is running
```

In Kubernetes or any other platform the same rule applies: run the broker you want, and set
`BROKER_URL` on `orders-api` and `notifier-worker` to point at it.

The example services keep their data in memory to stay dependency-free; a real
service would put a database behind the same repository class.

## Adding a new service

With Claude Code, ask it to create the service: the `new-service` skill
(`.claude/skills/new-service/`) does every step below and verifies the result. You can also run
its scaffold script yourself:

```bash
python3 .claude/skills/new-service/scripts/scaffold.py inventory-api --kind http --broker
python3 .claude/skills/new-service/scripts/scaffold.py audit-worker --kind worker \
    --event OrderPlaced --topic ORDER_PLACED_TOPIC
```

To do it by hand:

1. Copy the closest example (`apps/catalog-api` for HTTP, `apps/notifier-worker` for a worker)
   to `apps/<name>/` and rename the package, the `[project.scripts]` entry and the
   `src/<import_name>/` directory.
2. In its `Dockerfile`, change `ARG APP=` and `ENTRYPOINT` to the new name.
3. Add `apps/<name>/src` to `mypy_path` and the import name to ruff's `known-first-party` in the
   root `pyproject.toml`.
4. If it exchanges data with other services, put the models in `packages/contracts`.
5. Run `uv sync --all-packages`, commit the updated `uv.lock`, and add it to `compose.yaml`.
   If it uses the broker, give it `environment: *broker-env` and `depends_on: *broker-depends`
   so it follows whichever broker is selected, and copy the `redis` / `rabbitmq` extras and
   the `BROKER_EXTRAS` lines from `apps/notifier-worker`.

With `--broker` (or for any worker), the scaffold wires the compose entry to the shared
`*broker-env` / `*broker-depends` anchors and copies the broker extras into the app, so the new
service follows whichever broker is selected. HTTP services get the next free app port
(`8003`, `8004`, ...). CI picks the new member up automatically.
