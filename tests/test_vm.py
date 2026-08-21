from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import BinaryIO, cast

import pytest

import dotgen.vm as vm
from dotgen.vm import VmBackendUnavailable, VmCommandError, vm_session


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


def test_orb_prepares_passwordless_sudo_over_root_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr("dotgen.vm.subprocess.run", fake_run)
    script_name = "_PREPARE_PASSWORDLESS_SUDO"
    backend_name = "_OrbBackend"
    script = getattr(vm, script_name)
    assert "Defaults:%s !authenticate" in script
    assert "%s ALL=(ALL) NOPASSWD: ALL" in script
    assert "visudo -cf /etc/sudoers" in script
    backend = getattr(vm, backend_name)()
    handle = vm.VmHandle("vm-name", "test-user", backend)
    handle.prepare_passwordless_sudo()

    argv, kwargs = calls[0]
    assert argv == ["orb", "-m", "vm-name", "-u", "root", "bash", "-s", "--", "test-user"]
    assert kwargs == {"input": script, "capture_output": True, "text": True, "check": False, "timeout": 60}
    assert calls[1] == (
        ["orb", "-m", "vm-name", "-u", "test-user", "bash", "-c", "sudo -n -v"],
        {"capture_output": True, "text": True, "check": False, "timeout": 30},
    )


def test_tart_prepares_passwordless_sudo_with_fixture_password(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr("dotgen.vm.subprocess.run", fake_run)
    script_name = "_PREPARE_PASSWORDLESS_SUDO"
    backend_name = "_TartBackend"
    session_name = "_TartSession"
    sessions_name = "_sessions"
    script = getattr(vm, script_name)
    backend = getattr(vm, backend_name)()
    session = getattr(vm, session_name)(cast(subprocess.Popen[bytes], object()), "192.0.2.10")
    getattr(backend, sessions_name)["vm-name"] = session

    result = backend.prepare_passwordless_sudo("vm-name", "admin")

    assert result.returncode == 0
    argv, kwargs = calls[0]
    assert argv[-2] == "admin@192.0.2.10"
    assert argv[-1] == f"sudo -S -p '' bash -c {shlex.quote(script)} -- admin"
    assert kwargs == {"input": "admin\n", "capture_output": True, "text": True, "check": False, "timeout": 60}


def test_passwordless_sudo_prepare_failure_is_vm_command_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "out", "err")

    monkeypatch.setattr("dotgen.vm.subprocess.run", fake_run)
    backend_name = "_OrbBackend"
    backend = getattr(vm, backend_name)()
    handle = vm.VmHandle("vm-name", "test-user", backend)
    with pytest.raises(VmCommandError, match="prepare passwordless sudo") as raised:
        handle.prepare_passwordless_sudo()
    assert raised.value.stdout == "out"
    assert raised.value.stderr == "err"


def test_orb_prepares_subordinate_ids_over_root_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr("dotgen.vm.subprocess.run", fake_run)
    script_name = "_ORB_PREPARE_ROOTLESS_SUBIDS"
    backend_name = "_OrbBackend"
    script = getattr(vm, script_name)
    handle = vm.VmHandle("vm-name", "test-user", getattr(vm, backend_name)())
    handle.prepare_rootless_container_subids()
    argv, kwargs = calls[0]
    assert argv == ["orb", "-m", "vm-name", "-u", "root", "bash", "-s", "--", "test-user"]
    assert kwargs == {"input": script, "capture_output": True, "text": True, "check": False, "timeout": 60}


def test_orb_prepare_failure_is_vm_command_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "out", "err")

    monkeypatch.setattr("dotgen.vm.subprocess.run", fake_run)
    backend_name = "_OrbBackend"
    handle = vm.VmHandle("vm-name", "test-user", getattr(vm, backend_name)())
    with pytest.raises(VmCommandError, match="prepare rootless-container subordinate IDs") as raised:
        handle.prepare_rootless_container_subids()
    assert raised.value.stdout == "out"
    assert raised.value.stderr == "err"


@pytest.mark.parametrize("backend_name", ["_DockerBackend", "_TartBackend"])
def test_non_orb_backends_reject_subordinate_id_preparation(backend_name: str) -> None:
    backend = getattr(vm, backend_name)()
    with pytest.raises(VmBackendUnavailable, match="OrbStack Debian fixture"):
        backend.prepare_rootless_container_subids("vm", "user")


def _run_subid_fixture(
    tmp_path: Path,
    *,
    subuid: str = "",
    subgid: str = "",
    login_defs: str | None = None,
    fail: str = "",
    user: str = "alice",
    record: str = "alice:x:1000:1000::/home/alice:/bin/bash",
    id_value: str = "1000",
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    login_defs_file = tmp_path / "login.defs"
    uid_file = tmp_path / "subuid"
    gid_file = tmp_path / "subgid"
    login_defs_file.write_text(login_defs or "SUB_UID_MIN 100000\nSUB_UID_MAX 299999\nSUB_GID_MIN 300000\nSUB_GID_MAX 499999\n")
    uid_file.write_text(subuid)
    gid_file.write_text(subgid)
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "usermod").write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$LOG"
flag="$1"; range="$2"; account="$3"
[ "$FAIL" = "$flag" ] && exit 1
start="${range%-*}"; end="${range#*-}"; count=$((end-start+1))
case "$flag" in
--add-subuids) [ "$FAIL" != corrupt-uid ] && printf '%s:%s:%s\\n' "$account" "$start" "$count" >> "$SUBUID" || printf '%s:%s:1\\n' "$account" "$start" >> "$SUBUID" ;;
--add-subgids) [ "$FAIL" = drop-gid ] || printf '%s:%s:%s\\n' "$account" "$start" "$count" >> "$SUBGID" ;;
--del-subuids) grep -v "^$account:$start:$count$" "$SUBUID" > "$SUBUID.next" || true; mv "$SUBUID.next" "$SUBUID" ;;
--del-subgids) grep -v "^$account:$start:$count$" "$SUBGID" > "$SUBGID.next" || true; mv "$SUBGID.next" "$SUBGID" ;;
esac
"""
    )
    (fake / "usermod").chmod(0o755)
    (fake / "getent").write_text('#!/usr/bin/env bash\n[ "$GETENT_RECORD" = missing ] && exit 2\nprintf "%s\\n" "$GETENT_RECORD"\n')
    (fake / "id").write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$ID_VALUE"\n')
    for command in (fake / "getent", fake / "id"):
        command.chmod(0o755)
    fixture_script = cast(str, vars(vm)["_ORB_PREPARE_ROOTLESS_SUBIDS"])
    script = fixture_script.replace("/etc/login.defs", str(login_defs_file)).replace("/etc/subuid", str(uid_file)).replace("/etc/subgid", str(gid_file))
    log = tmp_path / "log"
    env = os.environ | {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "LOG": str(log),
        "SUBUID": str(uid_file),
        "SUBGID": str(gid_file),
        "FAIL": fail,
        "GETENT_RECORD": record,
        "ID_VALUE": id_value,
    }
    result = subprocess.run(["bash", "-s", "--", user], input=script, text=True, capture_output=True, env=env)
    return result, uid_file, gid_file, log


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def test_orb_subid_fixture_script_allocates_collision_free_ranges(tmp_path: Path) -> None:
    result, uid_file, gid_file, log = _run_subid_fixture(tmp_path, subuid="other:100000:65536\n", subgid="other:300000:65536\n")
    assert result.returncode == 0, result.stderr
    assert uid_file.read_text() == "other:100000:65536\nalice:165536:65536\n"
    assert gid_file.read_text() == "other:300000:65536\nalice:365536:65536\n"
    assert _calls(log) == ["--add-subuids 165536-231071 alice", "--add-subgids 365536-431071 alice"]


def test_orb_subid_fixture_skips_deploying_uid_and_gid_when_allocating(tmp_path: Path) -> None:
    bounds = "SUB_UID_MIN 1\nSUB_UID_MAX 200000\nSUB_GID_MIN 1\nSUB_GID_MAX 200000\n"
    result, uid_file, gid_file, log = _run_subid_fixture(
        tmp_path,
        login_defs=bounds,
        record="alice:x:1000:2000::/home/alice:/bin/bash",
    )
    assert result.returncode == 0, result.stderr
    assert uid_file.read_text() == "alice:1001:65536\n"
    assert gid_file.read_text() == "alice:2001:65536\n"
    assert _calls(log) == ["--add-subuids 1001-66536 alice", "--add-subgids 2001-67536 alice"]


@pytest.mark.parametrize(
    ("subuid", "subgid"),
    [
        ("alice:100000:65536\n", "alice:300000:65536\n"),
        ("1000:100000:65536\n", "1000:300000:65536\n"),
    ],
)
def test_orb_subid_fixture_reuses_exactly_one_username_or_numeric_form(tmp_path: Path, subuid: str, subgid: str) -> None:
    result, uid_file, gid_file, log = _run_subid_fixture(tmp_path, subuid=subuid, subgid=subgid)
    assert result.returncode == 0, result.stderr
    assert uid_file.read_text() == subuid and gid_file.read_text() == subgid
    assert _calls(log) == []


def test_orb_subid_fixture_uses_distinct_numeric_uid_and_gid_fallbacks(tmp_path: Path) -> None:
    subuid = "1000:100000:65536\n"
    subgid = "2000:300000:65536\n"
    result, uid_file, gid_file, log = _run_subid_fixture(
        tmp_path,
        subuid=subuid,
        subgid=subgid,
        record="alice:x:1000:2000::/home/alice:/bin/bash",
    )
    assert result.returncode == 0, result.stderr
    assert uid_file.read_text() == subuid and gid_file.read_text() == subgid
    assert _calls(log) == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"user": "root"}, "invalid account"),
        ({"record": "missing"}, "unknown account"),
        ({"record": "bob:x:1000:1000::/home/bob:/bin/bash"}, "invalid account record"),
        ({"record": "alice:x:0:1000::/home/alice:/bin/bash"}, "invalid account record"),
        ({"id_value": "999"}, "account UID mismatch"),
        ({"login_defs": "SUB_UID_MIN 100000\nSUB_UID_MAX 299999\nSUB_GID_MIN 300000\n"}, "missing or duplicate"),
        ({"login_defs": "SUB_UID_MIN 100000\nSUB_UID_MIN 100001\nSUB_UID_MAX 299999\nSUB_GID_MIN 300000\nSUB_GID_MAX 499999\n"}, "missing or duplicate"),
        ({"login_defs": "SUB_UID_MIN x\nSUB_UID_MAX 299999\nSUB_GID_MIN 300000\nSUB_GID_MAX 499999\n"}, "missing or duplicate"),
        ({"login_defs": "SUB_UID_MIN 100000\nSUB_UID_MAX 100001\nSUB_GID_MIN 300000\nSUB_GID_MAX 499999\n"}, "invalid subordinate-ID bounds"),
        ({"subuid": "bad\n"}, "invalid allocation record"),
        ({"subuid": "bob:4294967295:2\n"}, "invalid allocation record"),
        ({"subuid": "alice:100000:1\n"}, "short existing range"),
        ({"subuid": "alice:1:65536\n"}, "contains host ID"),
        ({"subuid": "1000:1:65536\n"}, "contains host ID"),
        ({"subuid": "alice:100000:65536\nalice:200000:65536\n"}, "multiple account ranges"),
        ({"subuid": "alice:100000:65536\n1000:200000:65536\n"}, "both username and numeric-principal"),
        ({"subuid": "alice:100000:65536\nbob:120000:65536\n"}, "overlaps foreign"),
        ({"subuid": "bob:100000:65536\nbob:165536:65536\n", "login_defs": "SUB_UID_MIN 100000\nSUB_UID_MAX 231071\nSUB_GID_MIN 300000\nSUB_GID_MAX 499999\n"}, "no available"),
    ],
)
def test_orb_subid_fixture_rejects_unsafe_inputs_before_add(tmp_path: Path, kwargs: dict[str, str], message: str) -> None:
    result, _uid_file, _gid_file, log = _run_subid_fixture(tmp_path, **kwargs)
    assert result.returncode != 0
    assert message in result.stderr
    assert _calls(log) == []


def test_orb_subid_fixture_advances_to_first_gap_and_preserves_existing_records(tmp_path: Path) -> None:
    subuid = "bob:100000:65536\ncarol:300000:65536\n"
    subgid = "bob:300000:65536\ncarol:500000:65536\n"
    result, uid_file, gid_file, log = _run_subid_fixture(tmp_path, subuid=subuid, subgid=subgid)
    assert result.returncode == 0, result.stderr
    assert uid_file.read_text().startswith(subuid)
    assert gid_file.read_text().startswith(subgid)
    assert _calls(log) == ["--add-subuids 165536-231071 alice", "--add-subgids 365536-431071 alice"]


@pytest.mark.parametrize(
    ("fail", "expected_calls"),
    [
        ("--add-subgids", ["--add-subuids 100000-165535 alice", "--add-subgids 300000-365535 alice", "--del-subuids 100000-165535 alice"]),
        ("drop-gid", ["--add-subuids 100000-165535 alice", "--add-subgids 300000-365535 alice", "--del-subgids 300000-365535 alice", "--del-subuids 100000-165535 alice"]),
    ],
)
def test_orb_subid_fixture_rolls_back_only_added_ranges_in_reverse(tmp_path: Path, fail: str, expected_calls: list[str]) -> None:
    original_uid = "bob:200000:65536\n"
    original_gid = "bob:400000:65536\n"
    result, uid_file, gid_file, log = _run_subid_fixture(tmp_path, subuid=original_uid, subgid=original_gid, fail=fail)
    assert result.returncode != 0
    assert _calls(log) == expected_calls
    assert uid_file.read_text() == original_uid
    assert gid_file.read_text() == original_gid
