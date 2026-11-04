# syntax=docker/dockerfile:1.7
# Build from the repo root so the workspace lockfile and sibling packages are in context:
#   docker build -f apps/orders-api/Dockerfile -t orders-api .
# Only this app and the workspace packages it depends on are installed.
#
# BROKER_EXTRAS chooses which broker client libraries go into the image. The default
# bakes in all of them, so one image can talk to any broker and BROKER_URL alone picks
# which (redis://, amqp://, tcp://). For a slimmer image, keep only the one you deploy:
#   docker build --build-arg BROKER_EXTRAS=rabbitmq -f apps/orders-api/Dockerfile -t orders-api .
# memory:// and tcp:// need no extra, so BROKER_EXTRAS="" is valid too.

ARG PYTHON_VERSION=3.13
ARG APP=orders-api
ARG BROKER_EXTRAS="redis rabbitmq"

FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder
ARG APP
ARG BROKER_EXTRAS
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# 1) Third-party deps only (cached layer, rebuilt only when the lock changes).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=packages,target=packages \
    --mount=type=bind,source=apps,target=apps \
    uv sync --frozen --no-dev --no-install-workspace --package ${APP} $(for e in ${BROKER_EXTRAS}; do printf -- "--extra %s " "$e"; done)

# 2) This app + its workspace deps, installed as real (non-editable) wheels.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package ${APP} $(for e in ${BROKER_EXTRAS}; do printf -- "--extra %s " "$e"; done)

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ARG APP
RUN useradd --create-home --uid 1000 app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
ENTRYPOINT ["orders-api"]
