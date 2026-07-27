import hashlib
import os
import stat
import subprocess
from pathlib import Path

from dotgen.components.bash_base import BashBase
from dotgen.components.stinkpot import Stinkpot
from dotgen.registry import ENVIRONMENTS
from dotgen.render import _decorate  # pyright: ignore[reportPrivateUsage]

_SOURCE_URL = "https://tangled.org/oppi.li/stinkpot/archive/cdf87ffcd36e96f3d49316d57fa17cc6ea8371df?format=tar.gz"
_SOURCE_SHA256 = "3482ea0c2e729de6e24067d97e91eb969cde2c3a3d9610ca2f0f745b2b20ef32"


def test_stinkpot_artifact_matrix_is_exact() -> None:
    expected = {
        "debian": {("linux", "amd64"), ("linux", "arm64")},
        "debian-docker": {("linux", "amd64"), ("linux", "arm64")},
        "macos": {("darwin", "arm64")},
    }
    for env_name, targets in expected.items():
        artifacts = Stinkpot().render(ENVIRONMENTS[env_name]).artifacts
        assert {(artifact.goos, artifact.goarch) for artifact in artifacts} == targets
        assert {artifact.dest for artifact in artifacts} == {f"artifacts/stinkpot/{goos}-{goarch}/stinkpot" for goos, goarch in targets}
        for artifact in artifacts:
            assert artifact.source_url == _SOURCE_URL
            assert artifact.source_sha256 == _SOURCE_SHA256
            assert artifact.go_version == "1.26.4"
            assert artifact.build_flags == ("-trimpath", "-buildvcs=false")
            assert artifact.ldflags == ("-s", "-w")
            assert artifact.mode == 0o755
            assert "darwin-amd64" not in artifact.dest


def test_stinkpot_registry_order_and_docker_go_exclusion() -> None:
    for env in ENVIRONMENTS.values():
        names = [component.name for component in env.components]
        assert names.index("core_utils") < names.index("stinkpot") < names.index("dotfiles_deploy")
    assert "go_lang" not in [component.name for component in ENVIRONMENTS["debian-docker"].components]


def _fake_stinkpot() -> bytes:
    return b"""#!/usr/bin/env bash
set -euo pipefail
data="${XDG_DATA_HOME:-$HOME/.local/share}/stinkpot"
case "${1-}" in
  list)
    mkdir -p "$data"
    : > "$data/history.db"
    ;;
  import)
    shift
    [ "${1-}" = --file ]
    [ "${STINKPOT_IMPORT_FAIL:-0}" != 1 ] || exit 7
    cp "$2" "$data/imported-history"
    printf 'import\n' >> "$HOME/import-calls"
    ;;
  init) printf '%s\n' ':' ;;
  *) exit 2 ;;
esac
"""


def _bundle(tmp_path: Path, rel: str) -> Path:
    root = tmp_path / "bundle"
    executable = root / "artifacts/stinkpot" / rel
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(_fake_stinkpot())
    executable.chmod(0o755)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    (root / "artifacts/stinkpot/SHA256SUMS").write_text(f"{digest}  {rel}\n")
    return root


def _run_setup(
    tmp_path: Path,
    *,
    mode: str,
    os_name: str,
    arch: str,
    home: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    home = home or tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    rel = {
        ("debian", "x86_64"): "linux-amd64/stinkpot",
        ("debian", "aarch64"): "linux-arm64/stinkpot",
        ("macos", "arm64"): "darwin-arm64/stinkpot",
    }.get((os_name, arch), "darwin-arm64/stinkpot")
    root = _bundle(tmp_path, rel)
    fragment = Stinkpot().render(ENVIRONMENTS["macos" if os_name == "macos" else "debian"])
    setup = _decorate("stinkpot", fragment).setup
    script = tmp_path / "run-setup.sh"
    script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
HOME={home!s}
export HOME
DIR={root!s}
DOTGEN_MODE={mode}
detect_os() {{ printf '%s\\n' {os_name}; }}
detect_arch() {{ printf '%s\\n' {arch}; }}
error() {{ printf 'ERROR: %s\\n' "$*" >&2; }}
ensure_dir() {{ mkdir -p "$1"; }}
component_begin() {{ :; }}
component_end() {{ :; }}
sha256sum() {{ python3 -c 'import hashlib,sys; p=sys.argv[1]; print(hashlib.sha256(open(p,"rb").read()).hexdigest(), p)' "$1"; }}
shasum() {{ shift 2; sha256sum "$1"; }}
{setup}
[ "$DOTGEN_MODE" != deploy ] || : > "$HOME/next-component-ran"
"""
    )
    env = os.environ.copy()
    env.update(extra_env or {})
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)


def test_stinkpot_deploy_installs_atomically_and_imports_once(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    legacy = home / ".bash_history"
    original = b"echo legacy\nprintf preserved\n"
    legacy.write_bytes(original)

    first = _run_setup(tmp_path, mode="deploy", os_name="debian", arch="x86_64", home=home)
    assert first.returncode == 0, first.stderr
    installed = home / "bin/stinkpot"
    marker = home / ".local/state/dotgen/stinkpot/bash-history-import-v1"
    data_dir = home / ".local/share/stinkpot"
    database = data_dir / "history.db"
    assert installed.is_file() and stat.S_IMODE(installed.stat().st_mode) == 0o755
    assert legacy.read_bytes() == original
    assert (data_dir / "imported-history").read_bytes() == original
    assert (home / "import-calls").read_text().splitlines() == ["import"]
    assert marker.is_file() and stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(database.stat().st_mode) == 0o600

    mtime = installed.stat().st_mtime_ns
    second = _run_setup(tmp_path, mode="deploy", os_name="debian", arch="x86_64", home=home)
    assert second.returncode == 0, second.stderr
    assert installed.stat().st_mtime_ns == mtime
    assert (home / "import-calls").read_text().splitlines() == ["import"]
    assert legacy.read_bytes() == original


def test_failed_import_prevents_marker_and_following_components(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    legacy = home / ".bash_history"
    original = b"must remain unchanged\n"
    legacy.write_bytes(original)

    result = _run_setup(
        tmp_path,
        mode="deploy",
        os_name="debian",
        arch="x86_64",
        home=home,
        extra_env={"STINKPOT_IMPORT_FAIL": "1"},
    )

    assert result.returncode != 0
    assert "history migration failed" in result.stderr
    assert legacy.read_bytes() == original
    assert not (home / ".local/state/dotgen/stinkpot/bash-history-import-v1").exists()
    assert not (home / "next-component-ran").exists()


def test_stinkpot_diff_is_read_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    result = _run_setup(tmp_path, mode="diff", os_name="macos", arch="arm64", home=home)
    assert result.returncode == 0, result.stderr
    assert "+ INSTALL" in result.stdout
    assert "+ MIGRATE" in result.stdout
    assert not (home / "bin/stinkpot").exists()
    assert not (home / ".local/share/stinkpot").exists()
    assert not (home / ".local/state/dotgen/stinkpot").exists()


def test_stinkpot_rejects_darwin_amd64_without_install(tmp_path: Path) -> None:
    home = tmp_path / "home"
    result = _run_setup(tmp_path, mode="deploy", os_name="macos", arch="x86_64", home=home)
    assert result.returncode != 0
    assert "does not support Darwin amd64" in result.stderr
    assert not (home / "bin/stinkpot").exists()


def _source_bashrc(tmp_path: Path, *, with_stinkpot: bool) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True)
    if with_stinkpot:
        executable = bin_dir / "stinkpot"
        executable.write_text(
            """#!/usr/bin/env bash
if [ "${1-}" = init ]; then
  cat <<'SH'
__stinkpot_record() { local exit=$?; STINKPOT_EXIT=$exit; }
__stinkpot_search() { :; }
case "$PROMPT_COMMAND" in
  *__stinkpot_record*) ;;
  *) PROMPT_COMMAND="__stinkpot_record${PROMPT_COMMAND:+; $PROMPT_COMMAND}" ;;
esac
bind -x '"\\C-r": __stinkpot_search'
SH
fi
"""
        )
        executable.chmod(0o755)
    bashrc = tmp_path / "bashrc"
    bashrc.write_text(
        f"""export PATH="$HOME/bin:$PATH"
bin_exists() {{ command -v "$1" >/dev/null 2>&1; }}
{BashBase().render(ENVIRONMENTS["debian"]).bashrc}
{Stinkpot().render(ENVIRONMENTS["debian"]).bashrc}
"""
    )
    command = f"""PROMPT_COMMAND=preexisting_hook
preexisting_hook() {{ :; }}
source {bashrc!s}
source {bashrc!s}
printf 'PROMPT=%s\\nHISTFILE=%s\\n' "$PROMPT_COMMAND" "${{HISTFILE-unset}}"
false
eval "$PROMPT_COMMAND"
printf 'EXIT=%s\\n' "${{STINKPOT_EXIT-unset}}"
bind -X | grep '__stinkpot_search' || true
"""
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(["bash", "--noprofile", "--norc", "-i", "-c", command], env=env, capture_output=True, text=True)


def test_stinkpot_bash_init_is_idempotent_and_recorder_first(tmp_path: Path) -> None:
    result = _source_bashrc(tmp_path, with_stinkpot=True)
    assert result.returncode == 0, result.stderr
    prompt = next(line.removeprefix("PROMPT=") for line in result.stdout.splitlines() if line.startswith("PROMPT="))
    assert prompt.split(";")[0] == "__stinkpot_record"
    assert prompt.count("__stinkpot_record") == 1
    assert prompt.count("set_win_title") == 1
    assert prompt.count("preexisting_hook") == 1
    assert "HISTFILE=/dev/null" in result.stdout
    assert "EXIT=1" in result.stdout
    assert result.stdout.count("__stinkpot_search") == 1


def test_missing_stinkpot_keeps_bash_histfile(tmp_path: Path) -> None:
    result = _source_bashrc(tmp_path, with_stinkpot=False)
    assert result.returncode == 0
    histfile = next(line.removeprefix("HISTFILE=") for line in result.stdout.splitlines() if line.startswith("HISTFILE="))
    assert histfile != "/dev/null"
    assert "stinkpot is unavailable" in result.stderr
