# syntax=docker/dockerfile:1.7
# Build from the repo root so the workspace lockfile and sibling packages are in context:
#   docker build -f apps/notifier-worker/Dockerfile -t notifier-worker .
# Only this app and the workspace packages it depends on are installed.

ARG PYTHON_VERSION=3.13
ARG APP=notifier-worker

FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder
ARG APP
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# 1) Third-party deps only (cached layer, rebuilt only when the lock changes).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=packages,target=packages \
    --mount=type=bind,source=apps,target=apps \
    uv sync --frozen --no-dev --no-install-workspace --package ${APP}

# 2) This app + its workspace deps, installed as real (non-editable) wheels.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package ${APP}

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ARG APP
RUN useradd --create-home --uid 1000 app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
ENTRYPOINT ["notifier-worker"]
