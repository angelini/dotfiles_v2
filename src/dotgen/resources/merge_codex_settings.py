"""Merge authored JSON settings into live Codex TOML, retaining comments."""

import json
import os
import sys
import tempfile
from collections.abc import MutableMapping
from pathlib import Path

import tomlkit


def merge(target, patch):
    for key, value in patch.items():
        if isinstance(value, dict):
            if not isinstance(target.get(key), MutableMapping):
                target[key] = tomlkit.table()
            merge(target[key], value)
        else:
            target[key] = value


def install(patch_path: Path, destination: Path) -> None:
    destination = Path(os.path.abspath(destination))
    for path in (destination, *destination.parents):
        if path.is_symlink():
            raise ValueError(f"symlink destination or ancestor: {path}")
    patch = json.loads(patch_path.read_text())
    if not isinstance(patch, dict):
        raise ValueError("settings patch must be a JSON object")
    document = tomlkit.parse(destination.read_text() if destination.exists() else "")
    merge(document, patch)
    content = tomlkit.dumps(document)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".codex-settings-", dir=destination.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    install(Path(sys.argv[1]), Path(sys.argv[2]))
