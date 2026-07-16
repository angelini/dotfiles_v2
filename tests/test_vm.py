from __future__ import annotations

import subprocess
from pathlib import Path
from typing import BinaryIO, cast

import pytest

from dotgen.vm import vm_session


def test_orb_push_streams_binary_file_over_stdin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "payload.bin"
    payload = b"\x00binary\xffpayload\n"
    src.write_bytes(payload)
    dest = "/tmp/file name;$(not-a-command)"
    calls: list[list[str]] = []
    push_kwargs: dict[str, object] = {}
    seen_payload = b""

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal seen_payload
        calls.append(argv)
        if "stdin" in kwargs:
            push_kwargs.update(kwargs)
            seen_payload = cast(BinaryIO, kwargs["stdin"]).read()
        return subprocess.CompletedProcess(argv, 0)

    def fake_which(_name: str) -> str:
        return "/usr/local/bin/orb"

    monkeypatch.setenv("USER", "test-user")
    monkeypatch.setattr("dotgen.vm.shutil.which", fake_which)
    monkeypatch.setattr("dotgen.vm.subprocess.run", fake_run)

    with vm_session("debian", "debian:bookworm") as handle:
        handle.push(src, dest)

    vm_name = calls[0][-1]
    assert calls[1] == [
        "orb",
        "-m",
        vm_name,
        "-u",
        "test-user",
        "sh",
        "-c",
        'cat > "$1"',
        "sh",
        dest,
    ]
    assert calls[2] == ["orb", "delete", "-f", vm_name]
    assert seen_payload == payload
    assert push_kwargs["capture_output"]
    assert push_kwargs["check"]
    assert "text" not in push_kwargs
    assert "input" not in push_kwargs
    assert str(src) not in calls[1]
