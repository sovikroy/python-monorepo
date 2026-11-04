"""Entry point for the example CLI app."""

import argparse
from collections.abc import Sequence

from core import greet


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cli", description="Print a greeting.")
    parser.add_argument("name", nargs="?", default="World", help="who to greet")
    args = parser.parse_args(argv)
    print(greet(args.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
