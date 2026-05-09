import argparse
from pathlib import Path

from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_all, build_env

DEFAULT_OUT = Path("dist")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dotgen")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="build a single environment")
    p_build.add_argument("env")

    sub.add_parser("build-all", help="build every environment")
    sub.add_parser("list-envs", help="print environment names")

    args = parser.parse_args(argv)

    if args.cmd == "build":
        if args.env not in ENVIRONMENTS:
            parser.error(f"unknown env: {args.env!r}; known: {sorted(ENVIRONMENTS)}")
        build_env(ENVIRONMENTS[args.env], args.out / args.env)
        return 0
    if args.cmd == "build-all":
        build_all(args.out)
        return 0
    if args.cmd == "list-envs":
        for name in ENVIRONMENTS:
            print(name)
        return 0
    parser.error(f"unknown command: {args.cmd!r}")
    return 2
