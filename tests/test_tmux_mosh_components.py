import os
import subprocess
from pathlib import Path

import pytest

from dotgen.components.mosh import Mosh
from dotgen.components.tmux import Tmux
from dotgen.components.tmuxinator import Tmuxinator
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
set -g detach-on-destroy off
set -g base-index 1
set -g renumber-windows on
set -g status-position bottom
set -g status-justify left
set -g status-interval 5
set -g status-style "bg=#1d1f21,fg=#c5c8c6"
set -g status-left-length 40
set -g status-right-length 80
set -g status-left "#[fg=#1d1f21,bg=#81a2be,bold] #S #[fg=#81a2be,bg=#1d1f21,nobold]"
set -g status-right "#[fg=#8abeb7,bg=#1d1f21]#[fg=#1d1f21,bg=#8abeb7] #H #[fg=#81a2be,bg=#8abeb7]#[fg=#1d1f21,bg=#81a2be,bold] %a %H:%M "
setw -g window-status-separator ""
setw -g window-status-format "#[fg=#969896,bg=#1d1f21] #I:#W#F "
setw -g window-status-current-format "#[fg=#1d1f21,bg=#b294bb]#[fg=#1d1f21,bg=#b294bb,bold] #I:#W#F #[fg=#b294bb,bg=#1d1f21,nobold]"
set -g message-style "bg=#f0c674,fg=#1d1f21,bold"
set -g mode-style "bg=#81a2be,fg=#1d1f21,bold"
bind r source-file ~/.tmux.conf \; display-message "tmux config reloaded"
bind | split-window -h -c "#{pane_current_path}"
bind - split-window -v -c "#{pane_current_path}"
bind c new-window -c "#{pane_current_path}"
"""

_EXPECTED_TMUXINATOR_DEFAULT = """name: <%= name %>
root: ~/repos/<%= name %>

startup_window: work
startup_pane: 0

windows:
  - work:
      layout: even-horizontal
      panes:
        - shell:
        - editor: hx .
  - agents: claude
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


def test_tmuxinator_applies_only_to_full_debian() -> None:
    component = Tmuxinator()

    assert component.applies_to(ENVIRONMENTS["debian"])
    assert not component.applies_to(ENVIRONMENTS["macos"])
    assert not component.applies_to(ENVIRONMENTS["debian-docker"])
    assert [c.name for c in ENVIRONMENTS["debian"].components].count("tmuxinator") == 1
    assert "tmuxinator" not in {c.name for c in ENVIRONMENTS["macos"].components}
    assert "tmuxinator" not in {c.name for c in ENVIRONMENTS["debian-docker"].components}


def test_tmux_render_contract() -> None:
    fragment = Tmux().render(ENVIRONMENTS["debian"])

    assert fragment.setup == 'install_package tmux\ninstall_config "$DIR/config/tmux/tmux.conf" "$HOME/.tmux.conf"\n'
    assert fragment.configs == (ConfigFile(dest="tmux/tmux.conf", content=_EXPECTED_TMUX_CONFIG),)
    config = fragment.configs[0].content
    assert config.splitlines()[0] == 'set -g default-terminal "tmux-256color"'
    assert "set -g base-index 1" in config
    assert "set -g renumber-windows on" in config
    assert "pane-base-index" not in config
    assert "#I:#W#F" in config
    for forbidden in ("allow-passthrough", "mode-keys", "prefix", "run-shell", "@plugin", "continuum", "resurrect"):
        assert forbidden not in config


def test_mosh_render_contract() -> None:
    debian = Mosh().render(ENVIRONMENTS["debian"])
    macos = Mosh().render(ENVIRONMENTS["macos"])

    assert debian.setup == macos.setup == "install_package mosh\n"
    assert debian.alias == ""
    assert "mosh-agent()" in macos.alias
    assert not debian.configs and not macos.configs


def test_tmuxinator_render_contract() -> None:
    fragment = Tmuxinator().render(ENVIRONMENTS["debian"])

    assert fragment.setup.startswith("install_package tmuxinator\n")
    assert 'config/tmuxinator/default.yml" "${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/tmuxinator/default.yml"' in fragment.setup
    assert 'dst="/usr/local/bin/dotgen-agent-session"' in fragment.setup
    assert fragment.configs[0] == ConfigFile(dest="tmuxinator/default.yml", content=_EXPECTED_TMUXINATOR_DEFAULT)
    helper = fragment.configs[1]
    assert helper.dest == "tmuxinator/dotgen-agent-session"
    assert helper.mode == 0o755
    assert helper.content.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert 'exec 9>"$lock"\nflock -x 9' in helper.content
    assert 'rm -f -- "$lock"' not in helper.content
    assert "focused_pane" not in fragment.configs[0].content
    assert sum(line.startswith("  - ") for line in fragment.configs[0].content.splitlines()) == 2


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


def _prepare_project_helper(
    tmp_path: Path,
    *,
    project: str = "project",
) -> tuple[Path, Path, dict[str, str], Path, Path]:
    home = tmp_path / "home"
    root = home / "repos" / project
    managed = home / ".config" / "dotgen" / "tmuxinator" / "default.yml"
    root.mkdir(parents=True)
    managed.parent.mkdir(parents=True)
    managed.write_text(_EXPECTED_TMUXINATOR_DEFAULT)

    helper = tmp_path / "dotgen-agent-session"
    helper.write_text(Tmuxinator().render(ENVIRONMENTS["debian"]).configs[1].content)
    helper.chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tmux_log = tmp_path / "tmux-calls"
    mux_log = tmp_path / "tmuxinator-calls"
    (bin_dir / "tmux").write_text(
        """#!/usr/bin/env bash
printf '%s\\0' "$@" >> "$TMUX_CALL_LOG"
printf '\\n' >> "$TMUX_CALL_LOG"
[ "${1-}" != has-session ] || exit "${TMUX_HAS_SESSION_RC:-1}"
"""
    )
    (bin_dir / "tmuxinator").write_text(
        """#!/usr/bin/env bash
printf '%s\\0' "$@" >> "$MUX_CALL_LOG"
printf '\\n' >> "$MUX_CALL_LOG"
case "${1-}" in
  new)
    project="$2"
    sed "s/<%= name %>/$project/g" "$TMUXINATOR_CONFIG/default.yml" > "$TMUXINATOR_CONFIG/$project.yml"
    ;;
  debug) exit "${TMUXINATOR_DEBUG_RC:-0}" ;;
esac
"""
    )
    (bin_dir / "flock").write_text("#!/usr/bin/env bash\nexit 0\n")
    for command in bin_dir.iterdir():
        command.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "TMUX_CALL_LOG": str(tmux_log),
        "MUX_CALL_LOG": str(mux_log),
        "TMUX_HAS_SESSION_RC": "1",
    }
    return helper, home, env, tmux_log, mux_log


def _run_project_helper(
    helper: Path,
    env: dict[str, str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(helper), *args], capture_output=True, text=True, env=env)


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


def test_project_helper_initializes_config_once(tmp_path: Path) -> None:
    helper, home, env, tmux_log, mux_log = _prepare_project_helper(tmp_path)

    result = _run_project_helper(helper, env, "init", "project")

    config = home / ".config" / "tmuxinator" / "project.yml"
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{config}\n"
    assert config.read_text() == _EXPECTED_TMUXINATOR_DEFAULT.replace("<%= name %>", "project")
    assert config.stat().st_mode & 0o777 == 0o644
    assert tmux_log.read_bytes() == b"has-session\0-t\0=project\0\n"
    assert mux_log.read_bytes() == b"new\0project\0\ndebug\0project\0\n"

    inode = config.stat().st_ino
    tmux_log.unlink()
    mux_log.unlink()
    repeated = _run_project_helper(helper, env, "init", "project")

    assert repeated.returncode == 0, repeated.stderr
    assert config.stat().st_ino == inode
    assert not tmux_log.exists()
    assert not mux_log.exists()


def test_project_helper_starts_existing_config_without_rewriting(tmp_path: Path) -> None:
    helper, home, env, tmux_log, mux_log = _prepare_project_helper(tmp_path)
    config = home / ".config" / "tmuxinator" / "project.yml"
    config.parent.mkdir(parents=True)
    config.write_text("sentinel\n")
    inode = config.stat().st_ino

    result = _run_project_helper(helper, env, "start", "project")

    assert result.returncode == 0, result.stderr
    assert config.read_text() == "sentinel\n"
    assert config.stat().st_ino == inode
    assert not tmux_log.exists()
    assert mux_log.read_bytes() == b"start\0project\0\n"


def test_project_helper_reset_refuses_active_session(tmp_path: Path) -> None:
    helper, home, env, tmux_log, mux_log = _prepare_project_helper(tmp_path)
    config = home / ".config" / "tmuxinator" / "project.yml"
    config.parent.mkdir(parents=True)
    config.write_text("sentinel\n")

    result = _run_project_helper(helper, {**env, "TMUX_HAS_SESSION_RC": "0"}, "reset", "project")

    assert result.returncode == 2
    assert "active project session" in result.stderr
    assert config.read_text() == "sentinel\n"
    assert tmux_log.read_bytes() == b"has-session\0-t\0=project\0\n"
    assert not mux_log.exists()


def test_project_helper_refuses_first_init_session_collision(tmp_path: Path) -> None:
    helper, home, env, tmux_log, mux_log = _prepare_project_helper(tmp_path)

    result = _run_project_helper(helper, {**env, "TMUX_HAS_SESSION_RC": "0"}, "init", "project")

    assert result.returncode == 2
    assert "already exists without a project config" in result.stderr
    assert not (home / ".config" / "tmuxinator" / "project.yml").exists()
    assert tmux_log.read_bytes() == b"has-session\0-t\0=project\0\n"
    assert not mux_log.exists()


def test_project_helper_rejects_symlink_managed_template(tmp_path: Path) -> None:
    helper, home, env, tmux_log, mux_log = _prepare_project_helper(tmp_path)
    managed = home / ".config" / "dotgen" / "tmuxinator" / "default.yml"
    target = home / "default.yml"
    target.write_text(_EXPECTED_TMUXINATOR_DEFAULT)
    managed.unlink()
    managed.symlink_to(target)

    result = _run_project_helper(helper, env, "init", "project")

    assert result.returncode == 2
    assert "managed template is missing or unsafe" in result.stderr
    assert not tmux_log.exists()
    assert not mux_log.exists()


def test_project_helper_failed_reset_preserves_config(tmp_path: Path) -> None:
    helper, home, env, _, _ = _prepare_project_helper(tmp_path)
    config = home / ".config" / "tmuxinator" / "project.yml"
    config.parent.mkdir(parents=True)
    config.write_text("sentinel\n")

    result = _run_project_helper(helper, {**env, "TMUXINATOR_DEBUG_RC": "1"}, "reset", "project")

    assert result.returncode == 1
    assert config.read_text() == "sentinel\n"
    assert not list(config.parent.glob(".project.yml.*"))


@pytest.mark.parametrize(
    "args",
    [
        ("start", "dev"),
        ("start", ""),
        ("start", "--no-attach"),
        ("start", "bad.name"),
        ("start", "bad/name"),
        ("start", "café"),
        ("unknown", "project"),
        ("start", "project", "extra"),
    ],
)
def test_project_helper_rejects_invalid_input_before_tools(tmp_path: Path, args: tuple[str, ...]) -> None:
    helper, _, env, tmux_log, mux_log = _prepare_project_helper(tmp_path)

    result = _run_project_helper(helper, env, *args)

    assert result.returncode == 2
    assert not tmux_log.exists()
    assert not mux_log.exists()


def test_project_helper_rejects_missing_or_symlink_root(tmp_path: Path) -> None:
    helper, home, env, tmux_log, mux_log = _prepare_project_helper(tmp_path)
    root = home / "repos" / "project"
    root.rmdir()

    missing = _run_project_helper(helper, env, "init", "project")
    assert missing.returncode == 2
    assert "project root is missing or unsafe" in missing.stderr

    target = home / "target"
    target.mkdir()
    root.symlink_to(target, target_is_directory=True)
    symlinked = _run_project_helper(helper, env, "init", "project")
    assert symlinked.returncode == 2
    assert "project root is missing or unsafe" in symlinked.stderr
    assert not tmux_log.exists()
    assert not mux_log.exists()


def test_project_helper_rejects_symlink_config(tmp_path: Path) -> None:
    helper, home, env, tmux_log, mux_log = _prepare_project_helper(tmp_path)
    config = home / ".config" / "tmuxinator" / "project.yml"
    config.parent.mkdir(parents=True)
    target = home / "project.yml"
    target.write_text("sentinel\n")
    config.symlink_to(target)

    result = _run_project_helper(helper, env, "init", "project")

    assert result.returncode == 2
    assert "project config is unsafe" in result.stderr
    assert target.read_text() == "sentinel\n"
    assert not tmux_log.exists()
    assert not mux_log.exists()


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("ta", b"new-session\0-A\0-s\0dev\0\n"),
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
            b"--\0server\0tmux\0new-session\0-A\0-s\0dev\0\n",
        ),
        (
            'mosh-agent "user@dev host" project-1',
            b"--\0user@dev host\0/usr/local/bin/dotgen-agent-session\0start\0project-1\0\n",
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
        "mosh-agent server --no-attach",
        "mosh-agent server dev",
        "mosh-agent server bad.name",
        "mosh-agent server bad/name",
        "mosh-agent server café",
        "mosh-agent server one extra",
    ],
)
def test_mosh_agent_rejects_invalid_input_before_mosh(tmp_path: Path, command: str) -> None:
    result, calls = _run_alias(tmp_path, Mosh().render(ENVIRONMENTS["macos"]).alias, command)

    assert result.returncode == 2
    assert calls == b""
