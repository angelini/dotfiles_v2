import os
import subprocess
from pathlib import Path

import pytest

from dotgen.components.mosh import Mosh
from dotgen.components.tmux import Tmux
from dotgen.fragment import ConfigFile
from dotgen.registry import ENVIRONMENTS

_EXPECTED_TMUX_CONFIG = r"""set -g default-terminal "tmux-256color"
set -as terminal-features ",xterm-ghostty:RGB:clipboard"
set -as terminal-features ",xterm-256color:RGB:clipboard"
set -as terminal-features ",xterm:RGB:clipboard"
set -as terminal-overrides ",xterm-256color:Ms=\\E]52;c;%p2%s\\007"
set -as terminal-overrides ",xterm:Ms=\\E]52;c;%p2%s\\007"
set -s set-clipboard on
set -s escape-time 10
set -g focus-events on
set -g mouse on
set -g history-limit 100000
"""


def test_tmux_and_mosh_apply_only_to_normal_environments() -> None:
    for component in (Tmux(), Mosh()):
        assert component.applies_to(ENVIRONMENTS["debian"])
        assert component.applies_to(ENVIRONMENTS["macos"])
        assert not component.applies_to(ENVIRONMENTS["debian-docker"])

    for env_name in ("debian", "macos"):
        names = [component.name for component in ENVIRONMENTS[env_name].components]
        assert names.count("tmux") == 1
        assert names.count("mosh") == 1
        assert names.index("stinkpot") < names.index("tmux") < names.index("mosh")

    docker_names = {component.name for component in ENVIRONMENTS["debian-docker"].components}
    assert {"tmux", "mosh"}.isdisjoint(docker_names)


def test_tmux_render_contract() -> None:
    fragment = Tmux().render(ENVIRONMENTS["debian"])

    assert fragment.setup == 'install_package tmux\ninstall_config "$DIR/config/tmux/tmux.conf" "$HOME/.tmux.conf"\n'
    assert fragment.configs == (ConfigFile(dest="tmux/tmux.conf", content=_EXPECTED_TMUX_CONFIG),)
    config = fragment.configs[0].content
    assert config.splitlines()[0] == 'set -g default-terminal "tmux-256color"'
    for forbidden in ("allow-passthrough", "mode-keys", "prefix", "run-shell", "@plugin", "continuum", "resurrect"):
        assert forbidden not in config


def test_mosh_render_contract() -> None:
    debian = Mosh().render(ENVIRONMENTS["debian"])
    macos = Mosh().render(ENVIRONMENTS["macos"])

    assert debian.setup == macos.setup == "install_package mosh\n"
    assert debian.alias == ""
    assert "mosh-agent()" in macos.alias
    assert not debian.configs and not macos.configs


def _fake_command(path: Path, name: str) -> None:
    executable = path / name
    executable.write_text(
        """#!/usr/bin/env bash
printf '%s\\0' "$@" >> "$CALL_LOG"
printf '\\n' >> "$CALL_LOG"
if [ "${1-}" = has-session ]; then
  exit "${TMUX_HAS_SESSION_RC:-0}"
fi
"""
    )
    executable.chmod(0o755)


def _run_alias(
    tmp_path: Path,
    alias: str,
    command: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], bytes]:
    alias_path = tmp_path / "aliases"
    alias_path.write_text(alias)
    log = tmp_path / "calls"
    _fake_command(tmp_path, "tmux")
    _fake_command(tmp_path, "mosh")
    env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "CALL_LOG": str(log),
        **(extra_env or {}),
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", f'source "$ALIAS_PATH"; {command}'],
        capture_output=True,
        text=True,
        env={**env, "ALIAS_PATH": str(alias_path)},
    )
    return result, log.read_bytes() if log.exists() else b""


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("ta", b"new-session\0-A\0-s\0agents\0\n"),
        ("ta project_1", b"new-session\0-A\0-s\0project_1\0\n"),
    ],
)
def test_ta_attaches_or_creates_outside_tmux(tmp_path: Path, command: str, expected: bytes) -> None:
    result, calls = _run_alias(tmp_path, Tmux().render(ENVIRONMENTS["debian"]).alias, command)

    assert result.returncode == 0, result.stderr
    assert calls == expected


@pytest.mark.parametrize(
    ("has_session_rc", "expected"),
    [
        ("0", b"has-session\0-t\0=project\0\nswitch-client\0-t\0=project\0\n"),
        (
            "1",
            b"has-session\0-t\0=project\0\nnew-session\0-d\0-s\0project\0\nswitch-client\0-t\0=project\0\n",
        ),
    ],
)
def test_ta_switches_without_nesting_inside_tmux(tmp_path: Path, has_session_rc: str, expected: bytes) -> None:
    result, calls = _run_alias(
        tmp_path,
        Tmux().render(ENVIRONMENTS["debian"]).alias,
        "ta project",
        extra_env={"TMUX": "/tmp/tmux", "TMUX_HAS_SESSION_RC": has_session_rc},
    )

    assert result.returncode == 0, result.stderr
    assert calls == expected


@pytest.mark.parametrize("command", ['ta ""', "ta bad.name", "ta café", "ta one two"])
def test_ta_rejects_invalid_input_before_tmux(tmp_path: Path, command: str) -> None:
    result, calls = _run_alias(tmp_path, Tmux().render(ENVIRONMENTS["debian"]).alias, command)

    assert result.returncode == 2
    assert calls == b""


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            "mosh-agent server",
            b"--\0server\0tmux\0new-session\0-A\0-s\0agents\0\n",
        ),
        (
            'mosh-agent "user@dev host" project-1',
            b"--\0user@dev host\0tmux\0new-session\0-A\0-s\0project-1\0\n",
        ),
    ],
)
def test_mosh_agent_preserves_remote_argv(tmp_path: Path, command: str, expected: bytes) -> None:
    result, calls = _run_alias(tmp_path, Mosh().render(ENVIRONMENTS["macos"]).alias, command)

    assert result.returncode == 0, result.stderr
    assert calls == expected


@pytest.mark.parametrize(
    "command",
    [
        "mosh-agent",
        'mosh-agent ""',
        "mosh-agent --bad",
        'mosh-agent server ""',
        "mosh-agent server bad.name",
        "mosh-agent server café",
        "mosh-agent server one extra",
    ],
)
def test_mosh_agent_rejects_invalid_input_before_mosh(tmp_path: Path, command: str) -> None:
    result, calls = _run_alias(tmp_path, Mosh().render(ENVIRONMENTS["macos"]).alias, command)

    assert result.returncode == 2
    assert calls == b""
