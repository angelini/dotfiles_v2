import os
import stat
import subprocess
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import pytest

from dotgen import cli
from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.render import required_secrets
from dotgen.secrets import all_keys
from dotgen.secrets_transfer import (
    COMPLETION_MARKER,
    REMOTE_INSTALLER,
    SecretsTransferError,
    parse_secrets_file,
    select_environment_values,
    select_file_values,
    send_payload,
    serialize_payload,
    standard_secrets_path,
    validate_target,
)
from dotgen.types import OS, PkgMgr


@dataclass(frozen=True)
class SecretComponent:
    name: str
    secrets: frozenset[str]
    enabled: bool = True

    def applies_to(self, env: Environment) -> bool:
        return self.enabled

    def render(self, env: Environment) -> Fragment:
        return Fragment(secrets=self.secrets)


def _write_secrets(tmp_path: Path, content: bytes) -> Path:
    path = tmp_path / "secrets.env"
    path.write_bytes(content)
    return path


def _run_remote(home: Path, payload: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["sh", "-c", REMOTE_INSTALLER],
        input=payload,
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )


def _required_key(env: Environment) -> frozenset[str]:
    return frozenset({"KEY"})


def _discard_send(target: str, payload: bytes, *, secret_keys: Collection[str]) -> None:
    pass


def test_required_secrets_uses_applicable_merged_components() -> None:
    env = Environment(
        "synthetic",
        OS.DEBIAN,
        PkgMgr.APT,
        components=(
            SecretComponent("first", frozenset({"GIT_USER_NAME"})),
            SecretComponent("direct_runtime", frozenset({"EXA_API_KEY"})),
            SecretComponent("disabled", frozenset({"AWS_ACCOUNT_ID"}), enabled=False),
        ),
    )

    assert required_secrets(env) == frozenset({"GIT_USER_NAME", "EXA_API_KEY"})
    assert required_secrets(env) != frozenset(all_keys())


def test_standard_secrets_path_prefers_xdg() -> None:
    assert standard_secrets_path({"XDG_CONFIG_HOME": "/custom", "HOME": "/home/me"}) == Path("/custom/dotgen/secrets.env")


def test_standard_secrets_path_falls_back_to_home() -> None:
    assert standard_secrets_path({"HOME": "/home/me"}) == Path("/home/me/.config/dotgen/secrets.env")


def test_standard_secrets_path_requires_home() -> None:
    with pytest.raises(SecretsTransferError, match="HOME is not set"):
        standard_secrets_path({})


def test_environment_selection_ignores_unrelated_values() -> None:
    selected = select_environment_values(
        {"GIT_USER_NAME", "GIT_USER_EMAIL"},
        {"GIT_USER_NAME": "Fake Name", "GIT_USER_EMAIL": "fake@example.invalid", "UNRELATED": "ignored"},
    )

    assert selected == {"GIT_USER_NAME": "Fake Name", "GIT_USER_EMAIL": "fake@example.invalid"}


@pytest.mark.parametrize("value", ["", "FAKE\nSENSITIVE", "FAKE\rSENSITIVE", "FAKE\x00SENSITIVE"])
def test_environment_selection_rejects_invalid_required_values_without_disclosure(value: str) -> None:
    with pytest.raises(SecretsTransferError) as caught:
        select_environment_values({"GITHUB_TOKEN"}, {"GITHUB_TOKEN": value})

    if value:
        assert value not in str(caught.value)


def test_environment_selection_reports_missing_key() -> None:
    with pytest.raises(SecretsTransferError, match="GITHUB_TOKEN"):
        select_environment_values({"GITHUB_TOKEN"}, {})


def test_file_parser_supports_exact_escapes_and_literal_shell_syntax(tmp_path: Path) -> None:
    path = _write_secrets(
        tmp_path,
        b'# full-line comment\n\nNAME="space and ! punctuation"\nTOKEN="quote: \\" slash: \\\\ $HOME $(touch nope) `touch nope`"\n',
    )

    parsed = parse_secrets_file(path)

    assert parsed["NAME"] == "space and ! punctuation"
    assert parsed["TOKEN"] == 'quote: " slash: \\ $HOME $(touch nope) `touch nope`'


def test_file_selection_ignores_extra_valid_assignments(tmp_path: Path) -> None:
    path = _write_secrets(tmp_path, b'REQUIRED="selected"\nEXTRA="ignored"\n')

    assert select_file_values({"REQUIRED"}, path) == {"REQUIRED": "selected"}


@pytest.mark.parametrize(
    "content",
    [
        b"KEY=value\n",
        b'lower="value"\n',
        b'KEY="bad\\n"\n',
        b'KEY="value" trailing\n',
        b'KEY="value" # comment\n',
        b'KEY="unterminated\n',
        b'_KEY="value"\n',
    ],
)
def test_file_parser_rejects_malformed_assignments(tmp_path: Path, content: bytes) -> None:
    path = _write_secrets(tmp_path, content)

    with pytest.raises(SecretsTransferError):
        parse_secrets_file(path)


def test_file_parser_rejects_duplicate_assignments(tmp_path: Path) -> None:
    path = _write_secrets(tmp_path, b'KEY="first"\nKEY="second"\n')

    with pytest.raises(SecretsTransferError, match="duplicate assignment for KEY") as caught:
        parse_secrets_file(path)

    assert "first" not in str(caught.value)
    assert "second" not in str(caught.value)


@pytest.mark.parametrize("content", [b'KEY="value"\r\n', b'KEY="value\x00"\n', b'KEY="\xff"\n'])
def test_file_parser_rejects_forbidden_bytes(tmp_path: Path, content: bytes) -> None:
    with pytest.raises(SecretsTransferError):
        parse_secrets_file(_write_secrets(tmp_path, content))


def test_invalid_utf8_error_does_not_retain_source_bytes(tmp_path: Path) -> None:
    fake_value = b'KEY="FAKE-SENSITIVE-\xff"\n'

    with pytest.raises(SecretsTransferError) as caught:
        parse_secrets_file(_write_secrets(tmp_path, fake_value))

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "FAKE-SENSITIVE" not in repr(caught.value)


def test_surrogate_value_fails_without_retaining_payload() -> None:
    fake_value = f"FAKE-{chr(0xDCFF)}-SENSITIVE"

    with pytest.raises(SecretsTransferError) as caught:
        serialize_payload({"KEY": fake_value})

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "FAKE-" not in repr(caught.value)


@pytest.mark.parametrize("content", [b'KEY=""\n', b'OTHER="value"\n'])
def test_file_selection_rejects_empty_or_missing_required_values(tmp_path: Path, content: bytes) -> None:
    with pytest.raises(SecretsTransferError):
        select_file_values({"KEY"}, _write_secrets(tmp_path, content))


def test_serialization_is_deterministic_and_round_trips_without_execution(tmp_path: Path) -> None:
    side_effect = tmp_path / "must-not-exist"
    command_text = f"$(touch {side_effect}) `touch {side_effect}` $HOME 'quoted'"
    values = {"Z_KEY": "spaces ! \\ slash", "A_KEY": command_text}

    first = serialize_payload(values)
    second = serialize_payload(dict(reversed(tuple(values.items()))))
    result = subprocess.run(
        ["bash", "-c", 'set -u; source /dev/stdin; printf "%s\\0%s" "$A_KEY" "$Z_KEY"'],
        input=first,
        capture_output=True,
        check=True,
    )

    assert first == second
    assert first.count(b"A_KEY=") == 1
    assert first.count(b"Z_KEY=") == 1
    assert first.endswith(f"{COMPLETION_MARKER}\n".encode())
    assert result.stdout.split(b"\x00") == [command_text.encode(), values["Z_KEY"].encode()]
    assert not side_effect.exists()


def test_send_payload_uses_stdin_only(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_value = "FAKE-SSH-SENTINEL-$()-`cmd`"
    payload = serialize_payload({"GITHUB_TOKEN": fake_value})
    seen_argv: list[str] = []
    seen_input = b""
    seen_environment: dict[str, str] = {}
    seen_check = True
    monkeypatch.setenv("GITHUB_TOKEN", fake_value)

    def fake_run(argv: list[str], *, input: bytes, env: dict[str, str], check: bool) -> subprocess.CompletedProcess[bytes]:
        nonlocal seen_input, seen_environment, seen_check
        seen_argv.extend(argv)
        seen_input = input
        seen_environment = env
        seen_check = check
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr("dotgen.secrets_transfer.subprocess.run", fake_run)

    send_payload("user@example.invalid", payload, secret_keys={"GITHUB_TOKEN"})

    assert all(fake_value not in argument for argument in seen_argv)
    assert seen_input is payload
    assert "GITHUB_TOKEN" not in seen_environment
    assert not seen_check
    assert seen_argv[:3] == ["ssh", "--", "user@example.invalid"]


@pytest.mark.parametrize("target", ["", "-oProxyCommand=bad", "user@host\nterminal", "user@host\x7f", "user@host\u202e"])
def test_target_validation_rejects_unsafe_targets(target: str) -> None:
    with pytest.raises(SecretsTransferError):
        validate_target(target)


def test_send_payload_propagates_ssh_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], *, input: bytes, env: dict[str, str], check: bool) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, 23)

    monkeypatch.setattr("dotgen.secrets_transfer.subprocess.run", fake_run)

    with pytest.raises(SecretsTransferError, match="status 23"):
        send_payload("user@example.invalid", serialize_payload({"KEY": "fake"}))


def test_send_payload_reports_ssh_launch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], *, input: bytes, env: dict[str, str], check: bool) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError

    monkeypatch.setattr("dotgen.secrets_transfer.subprocess.run", fake_run)

    with pytest.raises(SecretsTransferError, match="unable to start SSH"):
        send_payload("user@example.invalid", serialize_payload({"KEY": "fake"}))


def test_remote_installer_replaces_atomically_with_private_modes(tmp_path: Path) -> None:
    home = tmp_path / "home with spaces"
    destination_dir = home / ".config" / "dotgen"
    destination_dir.mkdir(parents=True)
    destination = destination_dir / "secrets.env"
    destination.write_text("old\n")
    payload = serialize_payload({"KEY": "fake value"})

    result = _run_remote(home, payload)

    assert result.returncode == 0
    assert destination.read_bytes() == payload
    assert stat.S_IMODE(destination_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert list(destination_dir.glob(".secrets.env.tmp.*")) == []


@pytest.mark.parametrize(
    "payload",
    [b"KEY='incomplete'\n", serialize_payload({"KEY": "fake"}).removesuffix(b"\n")],
)
def test_remote_installer_rejects_incomplete_payload_without_replacement(tmp_path: Path, payload: bytes) -> None:
    home = tmp_path / "home"
    destination_dir = home / ".config" / "dotgen"
    destination_dir.mkdir(parents=True)
    destination = destination_dir / "secrets.env"
    destination.write_bytes(b"existing\n")

    result = _run_remote(home, payload)

    assert result.returncode != 0
    assert destination.read_bytes() == b"existing\n"
    assert list(destination_dir.glob(".secrets.env.tmp.*")) == []


def test_remote_installer_rejects_non_file_destination(tmp_path: Path) -> None:
    home = tmp_path / "home"
    destination_dir = home / ".config" / "dotgen"
    destination = destination_dir / "secrets.env"
    destination.mkdir(parents=True)

    result = _run_remote(home, serialize_payload({"KEY": "fake"}))

    assert result.returncode != 0
    assert destination.is_dir()
    assert list(destination_dir.glob(".secrets.env.tmp.*")) == []


def test_cli_requires_exactly_one_source(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as missing:
        cli.main(["send-secrets", "debian", "user@host"])
    assert missing.value.code == 2

    with pytest.raises(SystemExit) as duplicate:
        cli.main(["send-secrets", "debian", "user@host", "--from-env", "--from-file"])
    assert duplicate.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_cli_uses_default_file_path_and_reports_only_env_and_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    default_path = tmp_path / "standard" / "secrets.env"
    seen: dict[str, object] = {}

    monkeypatch.setattr(cli, "required_secrets", _required_key)
    monkeypatch.setattr(cli, "standard_secrets_path", lambda: default_path)

    def fake_select(required: frozenset[str], path: Path) -> dict[str, str]:
        seen["path"] = path
        return {"KEY": "FAKE-CLI-SENTINEL"}

    def fake_send(target: str, payload: bytes, *, secret_keys: Collection[str]) -> None:
        seen["target"] = target
        seen["payload"] = payload
        seen["secret_keys"] = secret_keys

    monkeypatch.setattr(cli, "select_file_values", fake_select)
    monkeypatch.setattr(cli, "send_payload", fake_send)

    assert cli.main(["send-secrets", "debian", "user@host", "--from-file"]) == 0

    output = capsys.readouterr()
    assert seen["path"] == default_path
    assert seen["target"] == "user@host"
    assert seen["secret_keys"] == {"KEY": "FAKE-CLI-SENTINEL"}
    assert output.out == "sent secrets for debian to user@host\n"
    assert output.err == ""
    assert "FAKE-CLI-SENTINEL" not in output.out


def test_cli_uses_explicit_file_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.env"
    seen: dict[str, object] = {}
    monkeypatch.setattr(cli, "required_secrets", _required_key)

    def fake_select(required: frozenset[str], path: Path) -> dict[str, str]:
        seen["path"] = path
        return {"KEY": "fake"}

    monkeypatch.setattr(cli, "select_file_values", fake_select)
    monkeypatch.setattr(cli, "send_payload", _discard_send)

    assert cli.main(["send-secrets", "debian", "user@host", "--from-file", str(explicit)]) == 0
    assert seen["path"] == explicit


def test_cli_uses_exported_environment_source(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(cli, "required_secrets", _required_key)

    def fake_select(required: frozenset[str]) -> dict[str, str]:
        seen["required"] = required
        return {"KEY": "fake"}

    monkeypatch.setattr(cli, "select_environment_values", fake_select)
    monkeypatch.setattr(cli, "send_payload", _discard_send)

    assert cli.main(["send-secrets", "debian", "user@host", "--from-env"]) == 0
    assert seen["required"] == frozenset({"KEY"})


def test_cli_transfer_failure_is_value_free(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake_value = "FAKE-FAILURE-SENTINEL"
    monkeypatch.setattr(cli, "required_secrets", _required_key)

    def fake_select(required: frozenset[str]) -> dict[str, str]:
        return {"KEY": fake_value}

    monkeypatch.setattr(cli, "select_environment_values", fake_select)

    def fail_send(target: str, payload: bytes, *, secret_keys: Collection[str]) -> None:
        raise SecretsTransferError("SSH transfer failed with status 255")

    monkeypatch.setattr(cli, "send_payload", fail_send)

    with pytest.raises(SystemExit) as caught:
        cli.main(["send-secrets", "debian", "user@host", "--from-env"])

    output = capsys.readouterr()
    assert caught.value.code == 2
    assert fake_value not in output.out
    assert fake_value not in output.err
    assert "status 255" in output.err


def test_cli_rejects_unknown_environment(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["send-secrets", "unknown", "user@host", "--from-env"])

    assert caught.value.code == 2
    assert "unknown env" in capsys.readouterr().err
