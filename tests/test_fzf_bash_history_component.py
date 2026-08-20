import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from dotgen.components.bash_base import BashBase
from dotgen.components.fzf_bash_history import FzfBashHistory
from dotgen.registry import ENVIRONMENTS
from dotgen.render import _decorate  # pyright: ignore[reportPrivateUsage]


def _run_setup(home: Path) -> subprocess.CompletedProcess[str]:
    setup = _decorate("fzf_bash_history", FzfBashHistory().render(ENVIRONMENTS["debian"])).setup
    script = home.parent / "setup.sh"
    script.write_text(
        f"""set -euo pipefail
error() {{ printf 'ERROR: %s\\n' "$*" >&2; }}
component_begin() {{ :; }}
component_end() {{ :; }}
{setup}
"""
    )
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, env={**os.environ, "HOME": str(home)})


def _bashrc() -> str:
    env = ENVIRONMENTS["debian"]
    return BashBase().render(env).bashrc + "\n" + FzfBashHistory().render(env).bashrc


def _run_interactive(tmp_path: Path, command: str, *, fzf: bool = True, fzf_opts: str | None = None) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    bashrc = tmp_path / "bashrc"
    bashrc.write_text(_bashrc())
    env = {**os.environ, "HOME": str(home), "DOTGEN_BASHRC": str(bashrc)}
    if fzf_opts is not None:
        env["FZF_CTRL_R_OPTS"] = fzf_opts
    prelude = 'bin_exists() { command -v "$1" >/dev/null 2>&1; };' if fzf else "bin_exists() { return 1; };"
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-i", "-c", f"{prelude} {command}"],
        capture_output=True,
        text=True,
        env=env,
    )


def test_rendered_history_policy_and_registry_order() -> None:
    fragment = FzfBashHistory().render(ENVIRONMENTS["debian"])
    for setting in ("HISTFILE=~/.bash_history", "HISTSIZE=100000", "HISTFILESIZE=100000", "HISTCONTROL=ignoreboth", "shopt -s histappend"):
        assert setting in fragment.bashrc
    assert fragment.bashrc.index("history -a") < fragment.bashrc.index("history -n")
    for env in ENVIRONMENTS.values():
        names = [component.name for component in env.components]
        assert names.count("fzf_bash_history") == 1
        assert names.index("core_utils") + 1 == names.index("fzf_bash_history")


def test_setup_creates_secure_history_without_truncating(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    history = home / ".bash_history"
    original = b"echo preserved\n\x00bytes\n"
    history.write_bytes(original)
    history.chmod(0o666)

    result = _run_setup(home)

    assert result.returncode == 0, result.stderr
    assert history.read_bytes() == original
    assert stat.S_IMODE(history.stat().st_mode) == 0o600

    history.unlink()
    result = _run_setup(home)
    assert result.returncode == 0, result.stderr
    assert history.read_bytes() == b""
    assert stat.S_IMODE(history.stat().st_mode) == 0o600


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
def test_setup_rejects_unsafe_history_path_without_replacement(tmp_path: Path, kind: str) -> None:
    home = tmp_path / "home"
    home.mkdir()
    history = home / ".bash_history"
    target = tmp_path / "target"
    target.write_bytes(b"sentinel")
    if kind == "symlink":
        history.symlink_to(target)
    elif kind == "directory":
        history.mkdir()
    else:
        os.mkfifo(history)

    result = _run_setup(home)

    assert result.returncode != 0
    assert "unsafe Bash history path" in result.stderr
    if kind == "symlink":
        assert history.is_symlink()
        assert target.read_bytes() == b"sentinel"
    elif kind == "directory":
        assert history.is_dir()
    else:
        assert stat.S_ISFIFO(history.stat().st_mode)


def test_managed_prompt_hooks_are_ordered_idempotent_and_preserve_status(tmp_path: Path) -> None:
    result = _run_interactive(
        tmp_path,
        r'''preexisting_hook() { local status=$?; PREEXISTING_STATUS=$status; return "$status"; }
PROMPT_COMMAND=preexisting_hook
source "$DOTGEN_BASHRC"
source "$DOTGEN_BASHRC"
printf 'PROMPT=%s\n' "$PROMPT_COMMAND"
printf 'POLICY=%s:%s:%s:%s:%s\n' "$HISTFILE" "$HISTSIZE" "$HISTFILESIZE" "$HISTCONTROL" "$(shopt -q histappend; echo $?)"
false; __dotgen_history_sync; printf 'HISTORY_STATUS=%s\n' "$?"
false; set_win_title >/dev/null; printf 'TITLE_STATUS=%s\n' "$?"
false; eval "$PROMPT_COMMAND" >/dev/null; printf 'CHAIN_STATUS=%s PREEXISTING_STATUS=%s\n' "$?" "$PREEXISTING_STATUS"''',
    )

    assert result.returncode == 0, result.stderr
    prompt = next(line.removeprefix("PROMPT=") for line in result.stdout.splitlines() if line.startswith("PROMPT="))
    assert prompt.split(";") == ["__dotgen_history_sync", "set_win_title", "preexisting_hook"]
    assert "POLICY=" in result.stdout and ":100000:100000:ignoreboth:0" in result.stdout
    assert "HISTORY_STATUS=1" in result.stdout
    assert "TITLE_STATUS=1" in result.stdout
    assert "CHAIN_STATUS=1 PREEXISTING_STATUS=1" in result.stdout


def test_fzf_options_and_standard_bindings_are_idempotent(tmp_path: Path) -> None:
    if shutil.which("fzf") is None:
        pytest.skip("fzf is unavailable")
    result = _run_interactive(
        tmp_path,
        r'''source "$DOTGEN_BASHRC"
source "$DOTGEN_BASHRC"
printf 'OPTS=%s\n' "$FZF_CTRL_R_OPTS"
bind -m emacs-standard -X | grep -F '"\C-r"'
bind -m vi-command -X | grep -F '"\C-r"'
bind -m vi-insert -X | grep -F '"\C-r"'
bind -m emacs-standard -X | grep -F '"\C-t"'
bind -m emacs-standard -s | grep -F '"\ec"'
declare -f __fzf_history__ | grep -F -- "--bind=ctrl-r:toggle-sort"''',
        fzf_opts="--height 40% --border",
    )

    assert result.returncode == 0, result.stderr
    opts = next(line.removeprefix("OPTS=") for line in result.stdout.splitlines() if line.startswith("OPTS="))
    assert opts == "--height 40% --border --no-sort"
    assert opts.split().count("--no-sort") == 1
    assert result.stdout.count("__fzf_history__") == 3
    assert "fzf-file-widget" in result.stdout
    assert "__fzf_cd__" in result.stdout
    assert "--bind=ctrl-r:toggle-sort" in result.stdout


def test_existing_no_sort_option_is_preserved_exactly_once(tmp_path: Path) -> None:
    if shutil.which("fzf") is None:
        pytest.skip("fzf is unavailable")
    result = _run_interactive(
        tmp_path,
        'source "$DOTGEN_BASHRC"; printf "OPTS=%s\\n" "$FZF_CTRL_R_OPTS"',
        fzf_opts="--no-sort --height 50%",
    )

    assert result.returncode == 0, result.stderr
    assert "OPTS=--no-sort --height 50%" in result.stdout


def test_upstream_ctrl_r_keeps_newest_deduped_order_and_inserts_without_execution(tmp_path: Path) -> None:
    real_fzf = shutil.which("fzf")
    if real_fzf is None:
        pytest.skip("fzf is unavailable")
    version = subprocess.run([real_fzf, "--version"], capture_output=True, text=True, check=True).stdout.split()[0]
    if tuple(int(part) for part in version.split(".")[:2]) < (0, 60):
        pytest.skip("fzf 0.60+ is unavailable")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "fzf"
    wrapper.write_text(
        r"""#!/usr/bin/env bash
if [ "${1-}" = --bash ]; then
  exec "$REAL_FZF" --bash
fi
exec python3 -c 'import os,pathlib,sys
root=pathlib.Path(os.environ["FZF_CAPTURE"])
data=sys.stdin.buffer.read()
root.with_suffix(".input").write_bytes(data)
root.with_suffix(".args").write_text("\n".join(sys.argv[1:]))
root.with_suffix(".opts").write_text(os.environ.get("FZF_DEFAULT_OPTS", ""))
items=[item for item in data.split(b"\0") if item]
sys.stdout.buffer.write(items[0] + b"\n")' "$@"
"""
    )
    wrapper.chmod(0o755)
    capture = tmp_path / "capture"
    side_effect = tmp_path / "side-effect"
    home = tmp_path / "home"
    home.mkdir()
    bashrc = tmp_path / "bashrc"
    bashrc.write_text(_bashrc())
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "DOTGEN_BASHRC": str(bashrc),
        "REAL_FZF": real_fzf,
        "FZF_CAPTURE": str(capture),
        "SIDE_EFFECT": str(side_effect),
    }
    command = r'''bin_exists() { command -v "$1" >/dev/null 2>&1; }
source "$DOTGEN_BASHRC"
history -c
history -s "echo older"
history -s "touch $SIDE_EFFECT"
history -s "echo duplicate"
history -s "echo newest"
history -s "echo duplicate"
READLINE_LINE=seed-query
READLINE_POINT=4
__fzf_history__
printf 'LINE=%s POINT=%s\n' "$READLINE_LINE" "$READLINE_POINT"'''

    result = subprocess.run(["bash", "--noprofile", "--norc", "-i", "-c", command], capture_output=True, text=True, env=env)

    assert result.returncode == 0, result.stderr
    assert "LINE=echo duplicate" in result.stdout
    assert not side_effect.exists()
    history_input = capture.with_suffix(".input").read_bytes().split(b"\0")
    commands = [item.split(b"\t", 1)[1].decode().rstrip("\n\t") for item in history_input if b"\t" in item]
    assert commands.count("echo duplicate") == 1
    assert commands.index("echo newest") < commands.index("echo older")
    args = capture.with_suffix(".args").read_text().splitlines()
    assert args[-2:] == ["--query", "seed-query"]
    options = capture.with_suffix(".opts").read_text()
    assert "--scheme=history" in options
    assert "--bind=ctrl-r:toggle-sort" in options
    assert options.split().count("--no-sort") == 1


def test_missing_fzf_warns_once_keeps_native_binding_and_history_sync(tmp_path: Path) -> None:
    result = _run_interactive(
        tmp_path,
        r'''before=$(bind -m emacs-standard -s | grep '"\\C-r"' || true)
source "$DOTGEN_BASHRC"
source "$DOTGEN_BASHRC"
after=$(bind -m emacs-standard -s | grep '"\\C-r"' || true)
printf 'SAME=%s HISTFILE=%s SYNC=%s\n' "$([ "$before" = "$after" ]; echo $?)" "$HISTFILE" "$(type -t __dotgen_history_sync)"''',
        fzf=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr.count("fzf is unavailable") == 1
    assert "SAME=0" in result.stdout
    assert "HISTFILE=" in result.stdout and "/.bash_history" in result.stdout
    assert "SYNC=function" in result.stdout


def test_prompt_sync_publishes_for_an_already_running_peer(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    history = home / ".bash_history"
    history.touch()
    peer_script = r"""set -o history
HISTFILE="$HOME/.bash_history"
history -r
printf 'READY\n'
read -r _
history -n
history | grep -F 'dotgen-peer-command'
"""
    peer = subprocess.Popen(
        ["bash", "--noprofile", "--norc", "-c", peer_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )
    assert peer.stdout is not None and peer.stdout.readline().strip() == "READY"

    writer = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            'set -o history; HISTFILE="$HOME/.bash_history"; shopt -s histappend; history -s dotgen-peer-command; history -a',
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )
    assert writer.returncode == 0, writer.stderr
    assert peer.stdin is not None
    peer.stdin.write("continue\n")
    peer.stdin.flush()
    stdout, stderr = peer.communicate(timeout=10)
    assert peer.returncode == 0, stderr
    assert "dotgen-peer-command" in stdout


def test_new_shell_does_not_touch_legacy_stinkpot_data(tmp_path: Path) -> None:
    home = tmp_path / "home"
    legacy = {
        home / "bin/stinkpot": b"binary",
        home / ".local/share/stinkpot/history.db": b"database",
        home / ".local/share/stinkpot/history.db-wal": b"wal",
        home / ".local/share/stinkpot/history.db-shm": b"shm",
        home / ".local/state/dotgen/stinkpot/bash-history-import-v1": b"marker",
    }
    for path, content in legacy.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o640)
    before = {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in legacy}

    result = _run_interactive(tmp_path, 'source "$DOTGEN_BASHRC"', fzf=False)

    assert result.returncode == 0, result.stderr
    assert {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in legacy} == before
