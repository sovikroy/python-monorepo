#!/usr/bin/env python3
"""List the uv workspace packages affected by a change.

A package is affected when a file under its directory changed, or when it
depends (directly or transitively) on an affected workspace package. Changes
to shared files outside any package (root pyproject.toml, uv.lock, CI config,
...) mark every package as affected.

Standard library only, so it runs before any dependencies are installed.

Usage:
    python scripts/ci/affected.py --base <git-ref>    # diff <base>...HEAD
    python scripts/ci/affected.py --all               # every package
    python scripts/ci/affected.py --files a.py b.py   # explicit file list

Prints a JSON array of {"name", "path"} objects. With --github-output, also
writes `packages=<json>` and `any=<true|false>` to $GITHUB_OUTPUT.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Files outside any package that only matter to humans; changing them should
# not trigger a full run (fnmatch: `*` also matches `/`). Any other change
# outside a package triggers one.
IGNORED_GLOBS = ("*.md", "docs/*", "LICENSE*", ".gitignore", ".editorconfig")

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(req: str) -> str | None:
    match = _NAME_RE.match(req)
    return normalize(match.group(1)) if match else None


@dataclass
class Package:
    name: str
    path: str  # repo-relative, POSIX
    deps: set[str] = field(default_factory=set)


def load_workspace(root: Path) -> dict[str, Package]:
    data = tomllib.loads((root / "pyproject.toml").read_text())
    ws = data.get("tool", {}).get("uv", {}).get("workspace", {})
    members = ws.get("members", [])
    excludes = ws.get("exclude", [])

    excluded = {p.resolve() for pat in excludes for p in root.glob(pat)}
    dirs = sorted(
        {
            p.resolve()
            for pat in members
            for p in root.glob(pat)
            if (p / "pyproject.toml").is_file() and p.resolve() not in excluded
        }
    )

    raw: dict[str, tuple[str, list[str]]] = {}
    for d in dirs:
        if d == root.resolve():
            continue  # a root project isn't a separately testable member
        proj = tomllib.loads((d / "pyproject.toml").read_text())
        project = proj.get("project", {})
        reqs: list[str] = list(project.get("dependencies", []))
        for extra in project.get("optional-dependencies", {}).values():
            reqs += extra
        for group in proj.get("dependency-groups", {}).values():
            reqs += [r for r in group if isinstance(r, str)]
        rel = d.relative_to(root.resolve()).as_posix()
        raw[normalize(project["name"])] = (rel, reqs)

    packages: dict[str, Package] = {}
    for name, (rel, reqs) in raw.items():
        deps = {n for r in reqs if (n := requirement_name(r)) in raw and n != name}
        packages[name] = Package(name=name, path=rel, deps=deps)
    return packages


def changed_files(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def owner(path: str, packages: dict[str, Package]) -> Package | None:
    # Deepest match wins, in case members are nested.
    best = None
    for pkg in packages.values():
        inside = path == pkg.path or path.startswith(pkg.path + "/")
        if inside and (best is None or len(pkg.path) > len(best.path)):
            best = pkg
    return best


def affected(files: list[str], packages: dict[str, Package]) -> set[str]:
    hit: set[str] = set()
    for f in files:
        pkg = owner(f, packages)
        if pkg is not None:
            hit.add(pkg.name)
        elif not any(fnmatchcase(f, g) for g in IGNORED_GLOBS):
            return set(packages)  # shared file changed: run everything

    dependents: dict[str, set[str]] = {n: set() for n in packages}
    for pkg in packages.values():
        for dep in pkg.deps:
            dependents[dep].add(pkg.name)

    stack = list(hit)
    while stack:
        for parent in dependents[stack.pop()]:
            if parent not in hit:
                hit.add(parent)
                stack.append(parent)
    return hit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--base", help="git ref to diff against (merge-base)")
    src.add_argument("--all", action="store_true", help="select every package")
    src.add_argument("--files", nargs="*", help="explicit changed file list")
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args()

    packages = load_workspace(ROOT)
    if args.all:
        names = set(packages)
    else:
        files = args.files if args.files is not None else changed_files(args.base)
        names = affected(files, packages)

    result = [{"name": packages[n].name, "path": packages[n].path} for n in sorted(names)]
    payload = json.dumps(result)
    print(payload)
    for item in result:
        print(f"  affected: {item['name']} ({item['path']})", file=sys.stderr)

    if args.github_output:
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"packages={payload}\n")
            fh.write(f"any={'true' if result else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
