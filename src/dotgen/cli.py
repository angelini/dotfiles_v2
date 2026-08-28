import argparse
from pathlib import Path

from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_all, build_env, required_secrets
from dotgen.secrets_transfer import (
    SecretsTransferError,
    select_environment_values,
    select_file_values,
    send_payload,
    serialize_payload,
    standard_secrets_path,
)

DEFAULT_OUT = Path("dist")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dotgen")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="build a single environment")
    p_build.add_argument("env")

    sub.add_parser("build-all", help="build every environment")
    sub.add_parser("list-envs", help="print environment names")

    p_send = sub.add_parser("send-secrets", help="send environment-scoped secrets over SSH")
    p_send.add_argument("env")
    p_send.add_argument("target")
    source = p_send.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-env", action="store_true", help="read exported process environment values")
    source.add_argument(
        "--from-file",
        nargs="?",
        type=Path,
        default=argparse.SUPPRESS,
        help="read PATH, or the standard local secrets file when PATH is omitted",
    )

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
    if args.cmd == "send-secrets":
        if args.env not in ENVIRONMENTS:
            parser.error(f"unknown env: {args.env!r}; known: {sorted(ENVIRONMENTS)}")
        try:
            required = required_secrets(ENVIRONMENTS[args.env])
            if args.from_env:
                values = select_environment_values(required)
            else:
                path = args.from_file if args.from_file is not None else standard_secrets_path()
                values = select_file_values(required, path)
            send_payload(args.target, serialize_payload(values), secret_keys=values)
        except SecretsTransferError as error:
            parser.error(str(error))
        print(f"sent secrets for {args.env} to {args.target}")
        return 0
    parser.error(f"unknown command: {args.cmd!r}")
    return 2
