import os
import re
import subprocess
from collections.abc import Collection, Mapping
from pathlib import Path

COMPLETION_MARKER = "# dotgen-send-secrets-complete-v1"
_KEY_RE = re.compile(r"[A-Z][A-Z0-9_]*")

REMOTE_INSTALLER = f"""\
set -eu
umask 077

dir=$HOME/.config/dotgen
mkdir -p "$dir"
chmod 700 "$dir"

tmp=
i=0
while [ "$i" -lt 100 ]; do
    candidate=$dir/.secrets.env.tmp.$$.$i
    if (set -C; : > "$candidate") 2>/dev/null; then
        tmp=$candidate
        break
    fi
    i=$((i + 1))
done
if [ -z "$tmp" ]; then
    printf '%s\\n' 'dotgen: unable to create remote temporary file' >&2
    exit 1
fi

cleanup() {{
    rm -f "$tmp"
}}
trap cleanup 0
trap 'exit 1' 1 2 3 15

chmod 600 "$tmp"
cat > "$tmp"
last_line_and_frame=$(tail -n 1 "$tmp"; printf '%s' 'dotgen-frame-end')
expected_last_line='{COMPLETION_MARKER}
dotgen-frame-end'
if [ "$last_line_and_frame" != "$expected_last_line" ]; then
    printf '%s\\n' 'dotgen: incomplete secrets payload' >&2
    exit 1
fi

destination=$dir/secrets.env
if [ -e "$destination" ] && [ ! -f "$destination" ]; then
    printf '%s\\n' 'dotgen: remote destination is not a regular file' >&2
    exit 1
fi
mv -f "$tmp" "$destination"
trap - 0 1 2 3 15
"""


class SecretsTransferError(Exception):
    pass


def standard_secrets_path(environ: Mapping[str, str] | None = None) -> Path:
    source = os.environ if environ is None else environ
    xdg_config_home = source.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "dotgen" / "secrets.env"

    home = source.get("HOME")
    if not home:
        raise SecretsTransferError("cannot resolve secrets path: HOME is not set")
    return Path(home) / ".config" / "dotgen" / "secrets.env"


def select_environment_values(
    required: Collection[str], environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    source = os.environ if environ is None else environ
    missing = sorted(key for key in required if key not in source)
    if missing:
        raise SecretsTransferError(f"missing required secrets: {', '.join(missing)}")

    selected = {key: source[key] for key in required}
    _validate_selected_values(selected)
    return selected


def parse_secrets_file(path: Path) -> dict[str, str]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise SecretsTransferError(f"unable to read secrets file: {path}") from error

    if b"\x00" in raw:
        raise SecretsTransferError("secrets file contains NUL")
    if b"\r" in raw:
        raise SecretsTransferError("secrets file contains CR")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is None:
        raise SecretsTransferError("secrets file is not valid UTF-8")

    assignments: dict[str, str] = {}
    for line_number, line in enumerate(text.split("\n"), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, value = _parse_assignment(line, line_number)
        if key in assignments:
            raise SecretsTransferError(f"duplicate assignment for {key}")
        assignments[key] = value
    return assignments


def select_file_values(required: Collection[str], path: Path) -> dict[str, str]:
    assignments = parse_secrets_file(path)
    missing = sorted(key for key in required if key not in assignments)
    if missing:
        raise SecretsTransferError(f"missing required secrets: {', '.join(missing)}")

    selected = {key: assignments[key] for key in required}
    _validate_selected_values(selected)
    return selected


def serialize_payload(values: Mapping[str, str]) -> bytes:
    _validate_selected_values(values)
    lines: list[str] = []
    for key in sorted(values):
        if _KEY_RE.fullmatch(key) is None:
            raise SecretsTransferError(f"invalid secret key: {key}")
        lines.append(f"{key}={_shell_single_quote(values[key])}\n")
    lines.append(f"{COMPLETION_MARKER}\n")
    return "".join(lines).encode()


def validate_target(target: str) -> None:
    if not target:
        raise SecretsTransferError("SSH target must not be empty")
    if target.startswith("-"):
        raise SecretsTransferError("SSH target must not start with '-'")
    if any(not char.isprintable() for char in target):
        raise SecretsTransferError("SSH target must not contain control characters")


def send_payload(target: str, payload: bytes, *, secret_keys: Collection[str] = ()) -> None:
    validate_target(target)
    expected_suffix = f"{COMPLETION_MARKER}\n".encode()
    if not payload.endswith(expected_suffix):
        raise SecretsTransferError("secrets payload is incomplete")

    ssh_environment = os.environ.copy()
    for key in secret_keys:
        ssh_environment.pop(key, None)

    try:
        result = subprocess.run(
            ["ssh", "--", target, REMOTE_INSTALLER],
            input=payload,
            env=ssh_environment,
            check=False,
        )
    except OSError as error:
        raise SecretsTransferError("unable to start SSH") from error
    if result.returncode != 0:
        raise SecretsTransferError(f"SSH transfer failed with status {result.returncode}")


def _parse_assignment(line: str, line_number: int) -> tuple[str, str]:
    match = _KEY_RE.match(line)
    if match is None or line[match.end() : match.end() + 2] != '=\"':
        raise SecretsTransferError(f"malformed assignment on line {line_number}")

    key = match.group()
    index = match.end() + 2
    value: list[str] = []
    while index < len(line):
        char = line[index]
        if char == '"':
            if index != len(line) - 1:
                raise SecretsTransferError(f"trailing tokens on line {line_number}")
            return key, "".join(value)
        if char == "\\":
            index += 1
            if index >= len(line) or line[index] not in {'"', "\\"}:
                raise SecretsTransferError(f"invalid escape on line {line_number}")
            value.append(line[index])
        else:
            value.append(char)
        index += 1

    raise SecretsTransferError(f"unterminated assignment on line {line_number}")


def _validate_selected_values(values: Mapping[str, str]) -> None:
    for key, value in values.items():
        if not value:
            raise SecretsTransferError(f"required secret is empty: {key}")
        if "\n" in value or "\r" in value or "\x00" in value:
            raise SecretsTransferError(f"required secret contains a forbidden character: {key}")
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise SecretsTransferError(f"required secret is not valid Unicode: {key}")


def _shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
