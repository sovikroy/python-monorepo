# python-monorepo

A Python monorepo managed as a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/).
All members share one virtualenv and one `uv.lock`.

## Layout

```
.
├── pyproject.toml        # workspace root (virtual, not published) + ruff/mypy/pytest config
├── uv.lock               # single lockfile for the whole workspace
├── .python-version       # 3.13
├── packages/             # reusable libraries
│   └── core/             # example library  -> `import core`
│       ├── pyproject.toml
│       ├── src/core/
│       └── tests/
└── apps/                 # deployables (services, CLIs, jobs)
    └── cli/              # example app depending on `core`
        ├── pyproject.toml
        ├── src/cli/
        └── tests/
```

## Getting started

```bash
uv sync --all-packages        # create .venv with every member + dev tools
uv run pre-commit install     # enable git hooks
uv run cli Ada                # -> Hello, Ada!
```

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
docker build -f apps/cli/Dockerfile -t cli .
docker run --rm cli Ada
```

Because every app gets its own image, each one can be versioned, released and scaled
(replicas, autoscaling, resources) on its own. A change to `packages/core` only needs to
rebuild the apps that depend on it. To add a service, copy `apps/cli/Dockerfile`, change
`APP` and the `ENTRYPOINT`.
