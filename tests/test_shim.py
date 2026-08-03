import json
import os as os_module
import re
import shlex
import shutil
import signal
import subprocess
import tarfile
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from dotgen.shim import SHIM_FUNCTIONS, OSShim
from dotgen.types import OS

_DEF_RE = re.compile(r"^([a-z_][a-z_0-9]*)\(\) [\{(]", re.MULTILINE)


@pytest.fixture(params=list(OS), ids=[o.value for o in OS])
def shim_text(request: pytest.FixtureRequest) -> str:
    return OSShim(request.param).render()


def test_shim_is_bash_clean(tmp_path: Path, shim_text: str) -> None:
    f = tmp_path / "shim.sh"
    f.write_text(shim_text)
    subprocess.run(["bash", "-n", str(f)], check=True)


def test_shim_defines_full_function_set(shim_text: str) -> None:
    defined = set(_DEF_RE.findall(shim_text))
    assert defined == set(SHIM_FUNCTIONS)


def test_function_set_identical_across_oses() -> None:
    sets = {os: set(_DEF_RE.findall(OSShim(os).render())) for os in OS}
    canonical = sets[OS.MACOS]
    for os, found in sets.items():
        assert found == canonical, f"{os.value} differs: missing={canonical - found} extra={found - canonical}"


def _function_body(text: str, name: str) -> str:
    start = text.index(f"{name}() {{")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError(f"unbalanced braces in {name}")


def _run_shim_fn(tmp_path: Path, shim_text: str, call: str) -> str:
    script = tmp_path / "run.sh"
    script.write_text(f"{shim_text}\n{call}\n")
    return subprocess.check_output(["bash", str(script)]).decode()


def test_component_begin_uses_compact_progress(tmp_path: Path, shim_text: str) -> None:
    out = _run_shim_fn(tmp_path, shim_text, "component_begin aws")
    assert "---" not in out


def _macos_shim() -> str:
    return OSShim(OS.MACOS).render()


def _write_secrets(tmp_path: Path, body: str) -> None:
    (tmp_path / "dotgen").mkdir(exist_ok=True)
    (tmp_path / "dotgen" / "secrets.env").write_text(body)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def _run_template(
    tmp_path: Path,
    src: str,
    vars_list: str,
    *,
    secrets: str,
    requested_mode: str | None = None,
    tmpdir: Path | None = None,
    bin_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    _write_secrets(tmp_path, secrets)
    src_path = tmp_path / "src"
    src_path.write_text(src)
    dst_path = tmp_path / "dst"
    script = tmp_path / "run.sh"
    exports = [f"export XDG_CONFIG_HOME={shlex.quote(str(tmp_path))}"]
    if tmpdir is not None:
        tmpdir.mkdir(exist_ok=True)
        exports.append(f"export TMPDIR={shlex.quote(str(tmpdir))}")
    if bin_dir is not None:
        exports.append(f"export PATH={shlex.quote(str(bin_dir))}:$PATH")
    mode_arg = f" {requested_mode}" if requested_mode is not None else ""
    call = f"install_config_template {shlex.quote(str(src_path))} {shlex.quote(str(dst_path))} {shlex.quote(vars_list)}{mode_arg}"
    script.write_text(f"{_macos_shim()}\n{'\n'.join(exports)}\n{call}\n")
    return subprocess.run(["bash", str(script)], capture_output=True, text=True)


def _template_artifacts(tmp_path: Path, tmpdir: Path) -> list[Path]:
    return sorted((*tmp_path.glob(".dotgen-template.*"), *tmpdir.glob("dotgen-template.*")))


def test_install_config_template_renders_with_default_mode_and_cleans_up(tmp_path: Path) -> None:
    tmpdir = tmp_path / "tmp"
    res = _run_template(
        tmp_path,
        src="name=${GIT_USER_NAME}\nemail=${GIT_USER_EMAIL}\n",
        vars_list="GIT_USER_NAME GIT_USER_EMAIL",
        secrets='GIT_USER_NAME="Alice"\nGIT_USER_EMAIL="a@example.com"\n',
        tmpdir=tmpdir,
    )
    dst = tmp_path / "dst"
    assert res.returncode == 0, res.stderr
    assert dst.read_text() == "name=Alice\nemail=a@example.com\n"
    assert dst.stat().st_mode & 0o777 == 0o644
    assert _template_artifacts(tmp_path, tmpdir) == []


def test_install_config_template_installs_explicit_mode_and_repairs_drift(tmp_path: Path) -> None:
    dst = tmp_path / "dst"
    dst.write_text("token=new-secret\n")
    dst.chmod(0o644)
    res = _run_template(
        tmp_path,
        src="token=${TOKEN}\n",
        vars_list="TOKEN",
        secrets='TOKEN="new-secret"\n',
        requested_mode="0600",
    )
    assert res.returncode == 0, res.stderr
    assert dst.read_text() == "token=new-secret\n"
    assert dst.stat().st_mode & 0o777 == 0o600


def test_install_config_template_missing_secrets(tmp_path: Path) -> None:
    res = _run_template(
        tmp_path,
        src="name=${GIT_USER_NAME}\nemail=${GIT_USER_EMAIL}\n",
        vars_list="GIT_USER_NAME GIT_USER_EMAIL",
        secrets='GIT_USER_NAME="Alice"\n',
    )
    assert res.returncode != 0
    assert "GIT_USER_EMAIL" in res.stderr
    assert not (tmp_path / "dst").exists()


def test_install_config_template_whitelist_preserves_unrelated(tmp_path: Path) -> None:
    res = _run_template(
        tmp_path,
        src="name=${GIT_USER_NAME}\npath=$PATH\n",
        vars_list="GIT_USER_NAME",
        secrets='GIT_USER_NAME="Alice"\n',
    )
    assert res.returncode == 0, res.stderr
    out = (tmp_path / "dst").read_text()
    assert "Alice" in out
    assert "$PATH" in out


def test_install_config_template_rejects_invalid_mode_before_creating_temps(tmp_path: Path) -> None:
    tmpdir = tmp_path / "tmp"
    res = _run_template(
        tmp_path,
        src="token=${TOKEN}\n",
        vars_list="TOKEN",
        secrets='TOKEN="secret"\n',
        requested_mode="600",
        tmpdir=tmpdir,
    )
    assert res.returncode != 0
    assert "invalid mode" in res.stderr
    assert _template_artifacts(tmp_path, tmpdir) == []


@pytest.mark.parametrize("directory_symlink", [False, True], ids=["directory", "directory-symlink"])
def test_install_config_template_rejects_directory_targets_without_leaking(tmp_path: Path, directory_symlink: bool) -> None:
    dst = tmp_path / "dst"
    target_dir = tmp_path / "target-dir"
    if directory_symlink:
        target_dir.mkdir()
        dst.symlink_to(target_dir, target_is_directory=True)
    else:
        dst.mkdir()
        target_dir = dst
    tmpdir = tmp_path / "tmp"
    res = _run_template(
        tmp_path,
        src="token=${TOKEN}\n",
        vars_list="TOKEN",
        secrets='TOKEN="directory-secret-sentinel"\n',
        requested_mode="0600",
        tmpdir=tmpdir,
    )
    assert res.returncode != 0
    assert "destination is not a regular file" in res.stderr
    assert "directory-secret-sentinel" not in res.stdout + res.stderr
    assert list(target_dir.iterdir()) == []
    assert dst.is_symlink() is directory_symlink
    assert _template_artifacts(tmp_path, tmpdir) == []


@pytest.mark.parametrize("directory_symlink", [False, True], ids=["directory", "directory-symlink"])
def test_install_config_template_rechecks_directory_target_after_staging(tmp_path: Path, directory_symlink: bool) -> None:
    dst = tmp_path / "dst"
    target_dir = tmp_path / "target-dir" if directory_symlink else dst
    tmpdir = tmp_path / "tmp"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mutation = {
        False: f"mkdir {shlex.quote(str(dst))}",
        True: f"mkdir {shlex.quote(str(target_dir))}\nln -s {shlex.quote(str(target_dir))} {shlex.quote(str(dst))}",
    }[directory_symlink]
    _write_executable(
        bin_dir / "install",
        f'#!/usr/bin/env bash\ncp "$3" "$4"\nchmod "$2" "$4"\n{mutation}\n',
    )
    res = _run_template(
        tmp_path,
        src="token=${TOKEN}\n",
        vars_list="TOKEN",
        secrets='TOKEN="staged-secret-sentinel"\n',
        requested_mode="0600",
        tmpdir=tmpdir,
        bin_dir=bin_dir,
    )
    assert res.returncode != 0
    assert "destination is not a regular file" in res.stderr
    assert "staged-secret-sentinel" not in res.stdout + res.stderr
    assert list(target_dir.iterdir()) == []
    assert dst.is_symlink() is directory_symlink
    assert _template_artifacts(tmp_path, tmpdir) == []


def test_install_config_template_cleans_up_after_envsubst_failure(tmp_path: Path) -> None:
    tmpdir = tmp_path / "tmp"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "envsubst", "#!/usr/bin/env bash\nexit 41\n")
    res = _run_template(
        tmp_path,
        src="token=${TOKEN}\n",
        vars_list="TOKEN",
        secrets='TOKEN="secret"\n',
        tmpdir=tmpdir,
        bin_dir=bin_dir,
    )
    assert res.returncode != 0
    assert not (tmp_path / "dst").exists()
    assert _template_artifacts(tmp_path, tmpdir) == []


def test_install_config_template_install_failure_is_atomic_and_cleans_up(tmp_path: Path) -> None:
    dst = tmp_path / "dst"
    dst.write_text("old-secret\n")
    dst.chmod(0o640)
    tmpdir = tmp_path / "tmp"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "install", '#!/usr/bin/env bash\nprintf partial > "${@: -1}"\nexit 42\n')
    res = _run_template(
        tmp_path,
        src="token=${TOKEN}\n",
        vars_list="TOKEN",
        secrets='TOKEN="new-secret"\n',
        requested_mode="0600",
        tmpdir=tmpdir,
        bin_dir=bin_dir,
    )
    assert res.returncode != 0
    assert dst.read_text() == "old-secret\n"
    assert dst.stat().st_mode & 0o777 == 0o640
    assert _template_artifacts(tmp_path, tmpdir) == []


@pytest.mark.parametrize("envsubst_fails", [False, True], ids=["success", "failure"])
def test_install_config_template_preserves_caller_traps(tmp_path: Path, envsubst_fails: bool) -> None:
    _write_secrets(tmp_path, 'TOKEN="secret"\n')
    src = tmp_path / "src"
    src.write_text("token=${TOKEN}\n")
    bin_dir = tmp_path / "bin"
    path_export = ""
    if envsubst_fails:
        bin_dir.mkdir()
        _write_executable(bin_dir / "envsubst", "#!/usr/bin/env bash\nexit 41\n")
        path_export = f"export PATH={shlex.quote(str(bin_dir))}:$PATH\n"
    status_file = tmp_path / "status"
    script = tmp_path / "run-traps.sh"
    script.write_text(
        f"""{_macos_shim()}
export XDG_CONFIG_HOME={shlex.quote(str(tmp_path))}
{path_export}trap ':' EXIT
trap ':' HUP
trap ':' INT
trap ':' TERM
before="$(trap -p EXIT HUP INT TERM)"
install_config_template {shlex.quote(str(src))} {shlex.quote(str(tmp_path / "dst"))} 'TOKEN' 0600
status=$?
after="$(trap -p EXIT HUP INT TERM)"
[ "$before" = "$after" ] || exit 90
printf '%s' "$status" > {shlex.quote(str(status_file))}
"""
    )
    res = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    status = int(status_file.read_text())
    assert (status != 0) is envsubst_fails


@pytest.mark.parametrize(
    ("sig", "expected_status"),
    [(signal.SIGHUP, 129), (signal.SIGINT, 130), (signal.SIGTERM, 143)],
    ids=["hup", "int", "term"],
)
def test_install_config_template_signals_clean_up_and_preserve_caller_traps(tmp_path: Path, sig: signal.Signals, expected_status: int) -> None:
    _write_secrets(tmp_path, 'TOKEN="signal-secret"\n')
    src = tmp_path / "src"
    src.write_text("token=${TOKEN}\n")
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ready = tmp_path / "ready"
    status_file = tmp_path / "status"
    _write_executable(
        bin_dir / "envsubst",
        '#!/usr/bin/env bash\nprintf ready > "$READY_MARKER"\nwhile :; do sleep 1; done\n',
    )
    script = tmp_path / "run-signal.sh"
    script.write_text(
        f"""{_macos_shim()}
export XDG_CONFIG_HOME={shlex.quote(str(tmp_path))}
export TMPDIR={shlex.quote(str(tmpdir))}
export PATH={shlex.quote(str(bin_dir))}:$PATH
export READY_MARKER={shlex.quote(str(ready))}
trap ':' EXIT
trap ':' HUP
trap ':' INT
trap ':' TERM
before="$(trap -p EXIT HUP INT TERM)"
install_config_template {shlex.quote(str(src))} {shlex.quote(str(tmp_path / "dst"))} 'TOKEN' 0600
status=$?
after="$(trap -p EXIT HUP INT TERM)"
[ "$before" = "$after" ] || exit 90
printf '%s' "$status" > {shlex.quote(str(status_file))}
"""
    )
    proc = subprocess.Popen(["bash", str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    deadline = time.monotonic() + 5
    while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if not ready.exists():
        os_module.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
        pytest.fail(f"blocking envsubst did not become ready: stdout={stdout!r} stderr={stderr!r}")
    os_module.killpg(proc.pid, sig)
    stdout, stderr = proc.communicate(timeout=5)
    assert proc.returncode == 0, stderr
    assert int(status_file.read_text()) == expected_status
    assert "signal-secret" not in stdout + stderr
    assert _template_artifacts(tmp_path, tmpdir) == []


def test_install_config_template_missing_secrets_file(tmp_path: Path) -> None:
    src_path = tmp_path / "src"
    src_path.write_text("name=${GIT_USER_NAME}\n")
    dst_path = tmp_path / "dst"
    script = tmp_path / "run.sh"
    script.write_text(f"{_macos_shim()}\nexport XDG_CONFIG_HOME={tmp_path}\ninstall_config_template {src_path} {dst_path} 'GIT_USER_NAME'\n")
    res = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert res.returncode != 0
    assert "missing secrets file" in res.stderr
    assert not dst_path.exists()


def _run_json_patch(
    tmp_path: Path,
    patch: Path,
    dst: Path,
    *,
    requested_mode: str | None = None,
    tmpdir: Path | None = None,
    bin_dir: Path | None = None,
    prelude: str = "",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "run-json-patch.sh"
    mode_arg = f" {shlex.quote(requested_mode)}" if requested_mode is not None else ""
    script.write_text(f"set -uo pipefail\n{_macos_shim()}\n{prelude}\ninstall_json_patch {shlex.quote(str(patch))} {shlex.quote(str(dst))}{mode_arg}\n")
    env = os_module.environ.copy()
    if tmpdir is not None:
        tmpdir.mkdir(exist_ok=True)
        env["TMPDIR"] = str(tmpdir)
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["/bin/bash", str(script)], capture_output=True, text=True, env=env)


def _json_patch_artifacts(root: Path, tmpdir: Path) -> list[Path]:
    return sorted((*root.glob(".dotgen-json-patch.*"), *tmpdir.glob("dotgen-json-*.??????")))


def test_install_json_patch_creates_secure_destination_and_cleans_up(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    patch = root / "patch.json"
    dst = root / "nested" / "settings.json"
    tmpdir = root / "tmp"
    patch.write_text('{"managed":true}')

    result = _run_json_patch(root, patch, dst, tmpdir=tmpdir)

    assert result.returncode == 0, result.stderr
    assert json.loads(dst.read_text()) == {"managed": True}
    assert dst.stat().st_mode & 0o777 == 0o600
    assert _json_patch_artifacts(dst.parent, tmpdir) == []


def test_install_json_patch_merge_semantics(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    patch = root / "patch.json"
    dst = root / "settings.json"
    patch.write_text('{"nested":{"managed":2,"new":null},"array":[3],"leaf":{"value":1},"kind":"changed"}')
    dst.write_text('{"nested":{"managed":1,"keep":true},"array":[1,2],"leaf":"scalar","kind":{"old":true},"unmanaged":"keep"}')

    result = _run_json_patch(root, patch, dst)

    assert result.returncode == 0, result.stderr
    assert json.loads(dst.read_text()) == {
        "array": [3],
        "kind": "changed",
        "leaf": {"value": 1},
        "nested": {"keep": True, "managed": 2, "new": None},
        "unmanaged": "keep",
    }


def test_install_json_patch_empty_patch_preserves_values(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    patch = root / "patch.json"
    dst = root / "settings.json"
    patch.write_text("{}\n")
    dst.write_text('{"z":1,"nested":{"value":true}}\n')

    result = _run_json_patch(root, patch, dst)

    assert result.returncode == 0, result.stderr
    assert json.loads(dst.read_text()) == {"z": 1, "nested": {"value": True}}


@pytest.mark.parametrize(
    ("patch_text", "live_text", "message"),
    [
        ("{bad", "{}", "patch"),
        ("[]", "{}", "patch"),
        ("{}\n{}\n", "{}", "patch"),
        ('{"value":NaN}', "{}", "patch"),
        ('{"value":Infinity}', "{}", "patch"),
        ('{"value":-Infinity}', "{}", "patch"),
        ("{}", "{bad", "destination"),
        ("{}", "null", "destination"),
        ("{}", "{}\n{}\n", "destination"),
        ("{}", '{"value":NaN}', "destination"),
        ("{}", '{"value":Infinity}', "destination"),
        ("{}", '{"value":-Infinity}', "destination"),
    ],
)
def test_install_json_patch_rejects_invalid_json_objects(tmp_path: Path, patch_text: str, live_text: str, message: str) -> None:
    root = tmp_path.resolve()
    patch = root / "patch.json"
    dst = root / "settings.json"
    patch.write_text(patch_text)
    dst.write_text(live_text)
    before = dst.read_bytes()

    result = _run_json_patch(root, patch, dst)

    assert result.returncode != 0
    assert message in result.stderr
    assert dst.read_bytes() == before


def test_install_json_patch_rejects_missing_jq_and_invalid_mode_before_temps(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    patch = root / "patch.json"
    dst = root / "settings.json"
    tmpdir = root / "tmp"
    empty_bin = root / "empty-bin"
    patch.write_text("{}\n")
    empty_bin.mkdir()

    missing = _run_json_patch(root, patch, dst, tmpdir=tmpdir, bin_dir=empty_bin, extra_env={"PATH": str(empty_bin)})
    invalid = _run_json_patch(root, patch, dst, requested_mode="600", tmpdir=tmpdir)

    assert missing.returncode != 0 and "jq not installed" in missing.stderr
    assert invalid.returncode != 0 and "invalid mode" in invalid.stderr
    assert _json_patch_artifacts(root, tmpdir) == []


@pytest.mark.parametrize("kind", ["patch-directory", "patch-symlink", "destination-directory", "destination-symlink"])
def test_install_json_patch_rejects_non_regular_paths(tmp_path: Path, kind: str) -> None:
    root = tmp_path.resolve()
    real_patch = root / "real-patch.json"
    real_dst = root / "real-settings.json"
    patch = root / "patch.json"
    dst = root / "settings.json"
    real_patch.write_text("{}\n")
    real_dst.write_text("{}\n")
    patch.write_text("{}\n")
    if kind == "patch-directory":
        patch.unlink()
        patch.mkdir()
    elif kind == "patch-symlink":
        patch.unlink()
        patch.symlink_to(real_patch)
    elif kind == "destination-directory":
        dst.mkdir()
    else:
        dst.symlink_to(real_dst)

    result = _run_json_patch(root, patch, dst)

    assert result.returncode != 0
    assert "non-symlink file" in result.stderr


def test_install_json_patch_rejects_destination_ancestor_symlink(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    patch = root / "patch.json"
    real_parent = root / "real-parent"
    linked_parent = root / "linked-parent"
    patch.write_text("{}\n")
    real_parent.mkdir()
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    result = _run_json_patch(root, patch, linked_parent / "settings.json")

    assert result.returncode != 0
    assert "symlink destination ancestor" in result.stderr
    assert not (real_parent / "settings.json").exists()


def test_install_json_patch_repairs_mode_then_reruns_without_replacement(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    patch = root / "patch.json"
    dst = root / "settings.json"
    patch.write_text("{}\n")
    dst.write_text('{\n  "managed": true\n}\n')
    dst.chmod(0o644)

    first = _run_json_patch(root, patch, dst)
    inode = dst.stat().st_ino
    second = _run_json_patch(root, patch, dst)

    assert first.returncode == 0, first.stderr
    assert dst.stat().st_mode & 0o777 == 0o600
    assert second.returncode == 0, second.stderr
    assert dst.stat().st_ino == inode


@pytest.mark.parametrize("failure", ["jq", "install"])
def test_install_json_patch_failures_are_atomic_and_clean(tmp_path: Path, failure: str) -> None:
    root = tmp_path.resolve()
    patch = root / "patch.json"
    dst = root / "settings.json"
    tmpdir = root / "tmp"
    bin_dir = root / "bin"
    bin_dir.mkdir()
    patch.write_text('{"managed":"new"}\n')
    dst.write_text('{"managed":"old"}\n')
    dst.chmod(0o640)
    before = dst.read_bytes()
    if failure == "jq":
        jq = shutil.which("jq")
        assert jq is not None
        _write_executable(bin_dir / "jq", f'#!/usr/bin/env bash\n[ "$1" != -S ] && exec {shlex.quote(jq)} "$@"\nexit 41\n')
    else:
        _write_executable(bin_dir / "install", '#!/usr/bin/env bash\nprintf partial > "${@: -1}"\nexit 42\n')

    result = _run_json_patch(root, patch, dst, tmpdir=tmpdir, bin_dir=bin_dir)

    assert result.returncode != 0
    assert dst.read_bytes() == before
    assert dst.stat().st_mode & 0o777 == 0o640
    assert _json_patch_artifacts(root, tmpdir) == []


def test_install_json_patch_preserves_caller_traps(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    patch = root / "patch.json"
    dst = root / "settings.json"
    status_file = root / "status"
    patch.write_text("{}\n")
    script = root / "run-json-traps.sh"
    script.write_text(
        f"""{_macos_shim()}
trap ':' EXIT
trap ':' HUP
trap ':' INT
trap ':' TERM
before="$(trap -p EXIT HUP INT TERM)"
install_json_patch {shlex.quote(str(patch))} {shlex.quote(str(dst))} 0600
status=$?
after="$(trap -p EXIT HUP INT TERM)"
[ "$before" = "$after" ] || exit 90
printf '%s' "$status" > {shlex.quote(str(status_file))}
"""
    )

    result = subprocess.run(["/bin/bash", str(script)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert status_file.read_text() == "0"


def test_install_json_patch_signal_cleans_up_and_preserves_caller_traps(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    patch = root / "patch.json"
    dst = root / "settings.json"
    tmpdir = root / "tmp"
    bin_dir = root / "bin"
    ready = root / "ready"
    status_file = root / "status"
    patch.write_text("{}\n")
    tmpdir.mkdir()
    bin_dir.mkdir()
    jq = shutil.which("jq")
    assert jq is not None
    _write_executable(
        bin_dir / "jq",
        f'#!/usr/bin/env bash\nif [ "$1" != -S ]; then exec {shlex.quote(jq)} "$@"; fi\nprintf ready > "$READY_MARKER"\nwhile :; do sleep 1; done\n',
    )
    script = root / "run-json-signal.sh"
    script.write_text(
        f"""{_macos_shim()}
export TMPDIR={shlex.quote(str(tmpdir))}
export PATH={shlex.quote(str(bin_dir))}:$PATH
export READY_MARKER={shlex.quote(str(ready))}
trap ':' EXIT
trap ':' HUP
trap ':' INT
trap ':' TERM
before="$(trap -p EXIT HUP INT TERM)"
install_json_patch {shlex.quote(str(patch))} {shlex.quote(str(dst))} 0600
status=$?
after="$(trap -p EXIT HUP INT TERM)"
[ "$before" = "$after" ] || exit 90
printf '%s' "$status" > {shlex.quote(str(status_file))}
"""
    )
    proc = subprocess.Popen(["/bin/bash", str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    deadline = time.monotonic() + 5
    while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if not ready.exists():
        os_module.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
        pytest.fail(f"blocking jq did not become ready: stdout={stdout!r} stderr={stderr!r}")
    os_module.killpg(proc.pid, signal.SIGTERM)
    stdout, stderr = proc.communicate(timeout=5)

    assert proc.returncode == 0, stderr
    assert status_file.read_text() == "143"
    assert _json_patch_artifacts(root, tmpdir) == []
    assert not dst.exists()


def test_install_json_patch_rechecks_destination_before_publication(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    patch = root / "patch.json"
    dst = root / "settings.json"
    tmpdir = root / "tmp"
    bin_dir = root / "bin"
    patch.write_text('{"managed":true}\n')
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "install",
        '#!/usr/bin/env bash\ncp "$3" "$4"\nchmod "$2" "$4"\nmkdir "$MUTATE_DST"\n',
    )

    result = _run_json_patch(root, patch, dst, tmpdir=tmpdir, bin_dir=bin_dir, extra_env={"MUTATE_DST": str(dst)})

    assert result.returncode != 0
    assert "destination is not a regular" in result.stderr
    assert dst.is_dir()
    assert list(dst.iterdir()) == []
    assert _json_patch_artifacts(root, tmpdir) == []


def test_load_secrets_idempotent(tmp_path: Path) -> None:
    _write_secrets(tmp_path, 'COUNTER="$((${COUNTER:-0}+1))"\n')
    script = tmp_path / "run.sh"
    script.write_text(f'{_macos_shim()}\nexport XDG_CONFIG_HOME={tmp_path}\nload_secrets\nload_secrets\nprintf "%s" "$COUNTER"\n')
    res = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "1"


def test_debian_shim_uses_sudo_for_package_install(tmp_path: Path) -> None:
    shim = OSShim(OS.DEBIAN).render()
    script = tmp_path / "run.sh"
    script.write_text(
        f"""{shim}
pkg_installed() {{ return 1; }}
sudo() {{ printf 'sudo %s\\n' "$*"; }}
install_package mypkg
"""
    )

    res = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert res.returncode == 0
    assert "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y mypkg" in res.stdout


def test_debian_privileged_helpers_require_sudo() -> None:
    shim = OSShim(OS.DEBIAN).render()
    assert "sudo install -d -m 0755 /etc/apt/keyrings" in _function_body(shim, "add_repo")
    assert "sudo DEBIAN_FRONTEND=noninteractive apt-get update -y" in _function_body(shim, "update_pkg_index")
    assert 'sudo systemctl enable --now "$1"' in _function_body(shim, "service_enable")
    assert 'sudo DEBIAN_FRONTEND=noninteractive apt-get remove -y "${installed[@]}"' in _function_body(shim, "remove_packages")
    assert 'sudo systemctl mask --now "$@"' in _function_body(shim, "service_mask")


def test_macos_remove_packages_and_service_mask_are_stubs() -> None:
    macos = OSShim(OS.MACOS).render()
    assert "debian only" in _function_body(macos, "remove_packages")
    assert "debian only" in _function_body(macos, "service_mask")


def test_download_bin_reuses_matching_version_and_replaces_mismatch(tmp_path: Path) -> None:
    home = tmp_path / "home"
    target = home / "bin" / "tool"
    target.parent.mkdir(parents=True)
    _write_executable(target, '#!/usr/bin/env bash\n[ "$*" = "version --short" ] || exit 7\nprintf "tool v1.0.0\\n"\n')
    calls = tmp_path / "curl-calls"
    script = tmp_path / "run.sh"
    script.write_text(
        f"""set -euo pipefail
{_macos_shim()}
export HOME={shlex.quote(str(home))}
export CALLS={shlex.quote(str(calls))}
curl() {{
  printf x >> "$CALLS"
  while [ "$#" -gt 0 ]; do
    if [ "$1" = -o ]; then
      printf '#!/usr/bin/env bash\\n[ "$*" = "version --short" ] || exit 7\\nprintf "tool v2.0.0\\\\n"\\n' > "$2"
      return 0
    fi
    shift
  done
  return 2
}}
download_bin tool https://example.test/tool v2.0.0 version --short
download_bin tool https://example.test/tool v2.0.0 version --short
if bin_version_matches "$HOME/bin/tool" v2.0 version --short; then exit 9; fi
"""
    )

    result = subprocess.run(["bash", str(script)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert calls.read_text() == "x"
    assert subprocess.check_output([target, "version", "--short"], text=True) == "tool v2.0.0\n"
    assert result.stdout == ""


def test_download_tar_bin_reuses_matching_version(tmp_path: Path) -> None:
    home = tmp_path / "home"
    target = home / "bin" / "tool"
    target.parent.mkdir(parents=True)
    _write_executable(target, '#!/usr/bin/env bash\nprintf "v1.0.0\\n"\n')
    payload = tmp_path / "payload"
    payload.mkdir()
    archived_tool = payload / "tool"
    _write_executable(archived_tool, '#!/usr/bin/env bash\n[ "$*" = "--version" ] || exit 7\nprintf "v2.0.0\\n"\n')
    archive = tmp_path / "tool.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(archived_tool, arcname="nested/tool")
    calls = tmp_path / "curl-calls"
    script = tmp_path / "run.sh"
    script.write_text(
        f"""set -euo pipefail
{_macos_shim()}
export HOME={shlex.quote(str(home))}
export ARCHIVE={shlex.quote(str(archive))}
export CALLS={shlex.quote(str(calls))}
curl() {{
  printf x >> "$CALLS"
  command cat "$ARCHIVE"
}}
download_tar_bin tool https://example.test/tool.tar.gz nested/tool v2.0.0 --version
download_tar_bin tool https://example.test/tool.tar.gz nested/tool v2.0.0 --version
"""
    )

    result = subprocess.run(["bash", str(script)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert calls.read_text() == "x"
    assert subprocess.check_output([target, "--version"], text=True) == "v2.0.0\n"


def test_npm_install_activates_fnm_and_batches_packages(tmp_path: Path) -> None:
    body = _function_body(OSShim(OS.DEBIAN).render(), "install_npm_global")
    assert 'fnm_bin="$HOME/.local/share/fnm/fnm"' in body
    assert 'eval "$("$fnm_bin" env --shell bash)"' in body
    assert 'error "npm unavailable; node_fnm must run before npm installs"' in body
    assert 'npm install -g "$@"' in body
    calls = tmp_path / "npm-calls"
    script = tmp_path / "run.sh"
    script.write_text(
        f"""set -euo pipefail
{_macos_shim()}
export CALLS={shlex.quote(str(calls))}
npm() {{ printf '%s\\n' "$*" >> "$CALLS"; }}
install_npm_global pkg-one @scope/pkg-two
"""
    )

    result = subprocess.run(["bash", str(script)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert calls.read_text() == "install -g pkg-one @scope/pkg-two\n"
    assert result.stdout == ""


def _vendor_src(root: Path) -> Path:
    src = root / "src"
    (src / "nested dir").mkdir(parents=True)
    (src / "a.txt").write_text("a\n")
    (src / "nested dir" / "b file.txt").write_text("b\n")
    script = src / "run.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    return src


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _call(src: Path, dst: Path) -> str:
    return f'install_config_dir "{src}" "{dst}"'


def _managed_call(src: Path, dst: Path, identity: str = "fixture", *preserved: str) -> str:
    return "install_config_dir " + " ".join(shlex.quote(str(value)) for value in (src, dst, identity, *preserved))


def _managed_manifest(state: Path, identity: str) -> Path:
    return state / "dotgen" / "install-config-dir" / f"{identity}.manifest"


def _manifest_records(path: Path) -> list[bytes]:
    raw = path.read_bytes()
    assert raw.endswith(b"\0")
    return raw.split(b"\0")[:-1]


def _write_manifest(path: Path, records: list[bytes], trailing_nul: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0".join(records) + (b"\0" if trailing_nul else b""))


def _run_managed(tmp_path: Path, shim_text: str, call: str, *, prelude: str = "") -> subprocess.CompletedProcess[str]:
    script = tmp_path / "managed.sh"
    script.write_text(f"set -euo pipefail\n{shim_text}\n{prelude}\n{call}\n")
    env = os_module.environ | {"XDG_STATE_HOME": str(tmp_path / "state")}
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)


def test_install_config_dir_deploy_overlays_contents(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    (dst / "git-like").mkdir(parents=True)
    (dst / "git-like" / "HEAD").write_text("ref\n")
    (dst / "unmanaged.txt").write_text("keep\n")

    out = _run_shim_fn(tmp_path, shim_text, _call(src, dst))

    assert out == ""
    assert (dst / "a.txt").read_text() == "a\n"
    assert (dst / "nested dir" / "b file.txt").read_text() == "b\n"
    assert (dst / "run.sh").stat().st_mode & 0o111
    assert (dst / "git-like" / "HEAD").read_text() == "ref\n"
    assert (dst / "unmanaged.txt").read_text() == "keep\n"
    assert not (dst / "src").exists()


def test_install_config_dir_deploy_rerun_is_noop(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    _run_shim_fn(tmp_path, shim_text, _call(src, dst))
    first = _tree(dst)

    out = _run_shim_fn(tmp_path, shim_text, _call(src, dst))

    assert out == ""
    assert _tree(dst) == first


def _run_shim_checked(tmp_path: Path, shim_text: str, call: str) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "run.sh"
    script.write_text(f"set -euo pipefail\n{shim_text}\n{call}\n")
    return subprocess.run(["bash", str(script)], capture_output=True, text=True)


def test_install_config_dir_deploy_refuses_file_over_target_directory(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    (dst / "a.txt").mkdir(parents=True)
    (dst / "a.txt" / "unmanaged.txt").write_text("keep\n")

    res = _run_shim_checked(tmp_path, shim_text, _call(src, dst))

    assert res.returncode != 0
    assert f"{dst}/a.txt" in res.stderr
    assert (dst / "a.txt").is_dir()
    assert (dst / "a.txt" / "unmanaged.txt").read_text() == "keep\n"
    assert not (dst / "a.txt" / "a.txt").exists()
    assert not (dst / "run.sh").exists()


def test_install_config_dir_deploy_refuses_directory_over_target_file(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "nested dir").write_text("i am a file\n")

    res = _run_shim_checked(tmp_path, shim_text, _call(src, dst))

    assert res.returncode != 0
    assert f"{dst}/nested dir" in res.stderr
    assert (dst / "nested dir").read_text() == "i am a file\n"
    assert not (dst / "a.txt").exists()


def test_install_config_dir_fails_on_missing_source(tmp_path: Path, shim_text: str) -> None:
    src = tmp_path / "nope"
    dst = tmp_path / "dst"

    res = _run_shim_checked(tmp_path, shim_text, _call(src, dst))
    assert res.returncode != 0
    assert "missing source directory" in res.stderr
    assert not dst.exists()


def test_install_config_dir_handles_empty_source(tmp_path: Path, shim_text: str) -> None:
    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"

    first = _run_shim_checked(tmp_path, shim_text, _call(src, dst))
    assert first.returncode == 0, first.stderr
    assert dst.is_dir()
    assert _run_shim_checked(tmp_path, shim_text, _call(src, dst)).stdout == ""


def test_install_config_dir_managed_publish_update_and_preservation(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    (dst / "unmanaged" / "empty").mkdir(parents=True)
    (dst / "unmanaged.txt").write_text("keep\n")
    (dst / "git-like").mkdir()
    (dst / "git-like" / "HEAD").write_text("ref\n")
    first = _run_managed(tmp_path, shim_text, _managed_call(src, dst))
    assert first.returncode == 0, first.stderr
    state = tmp_path / "state"
    manifest = _managed_manifest(state, "fixture")
    expected = {os_module.fsencode(str(path.relative_to(src))) for path in src.rglob("*") if path.is_file()}
    records = _manifest_records(manifest)
    assert records[:2] == [b"dotgen-install-config-dir-v1", os_module.fsencode(str(dst))]
    assert set(records[2:]) == expected
    assert (dst / "run.sh").stat().st_mode & 0o111
    assert (dst / "unmanaged.txt").read_text() == "keep\n"
    assert (dst / "git-like" / "HEAD").read_text() == "ref\n"
    before_manifest = manifest.read_bytes()
    assert _run_managed(tmp_path, shim_text, _managed_call(src, dst)).returncode == 0
    assert manifest.read_bytes() == before_manifest

    (dst / "a.txt").write_text("drifted\n")
    (src / "a.txt").unlink()
    (src / "nested dir" / "b file.txt").unlink()
    (dst / "nested dir" / "b file.txt").unlink()
    (src / "new.txt").write_text("new\n")
    (dst / "run.sh").chmod(0o644)
    updated = _run_managed(tmp_path, shim_text, _managed_call(src, dst))
    assert updated.returncode == 0, updated.stderr
    assert not (dst / "a.txt").exists()
    assert not (dst / "nested dir" / "b file.txt").exists()
    assert (dst / "new.txt").read_text() == "new\n"
    assert (dst / "run.sh").stat().st_mode & 0o111
    assert (dst / "unmanaged.txt").read_text() == "keep\n"
    assert (dst / "unmanaged" / "empty").is_dir()
    assert (dst / "git-like").is_dir()
    assert set(_manifest_records(manifest)[2:]) == {os_module.fsencode(str(path.relative_to(src))) for path in src.rglob("*") if path.is_file()}


def test_install_config_dir_managed_releases_preserved_path(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    settings_src = src / "settings.json"
    settings_src.write_text('{"managed":true}\n')
    dst = tmp_path / "dst"
    assert _run_managed(tmp_path, shim_text, _managed_call(src, dst)).returncode == 0
    settings_dst = dst / "settings.json"
    settings_dst.write_text('{"managed":true,"unmanaged":"keep"}\n')
    settings_src.unlink()
    manifest = _managed_manifest(tmp_path / "state", "fixture")

    released = _run_managed(tmp_path, shim_text, _managed_call(src, dst, "fixture", "settings.json"))

    assert released.returncode == 0, released.stderr
    assert settings_dst.read_text() == '{"managed":true,"unmanaged":"keep"}\n'
    assert b"settings.json" not in _manifest_records(manifest)[2:]
    manifest_bytes = manifest.read_bytes()
    settings_inode = settings_dst.stat().st_ino
    rerun = _run_managed(tmp_path, shim_text, _managed_call(src, dst, "fixture", "settings.json"))
    assert rerun.returncode == 0, rerun.stderr
    assert manifest.read_bytes() == manifest_bytes
    assert settings_dst.stat().st_ino == settings_inode


def test_install_config_dir_preserved_path_does_not_disable_other_retired_deletions(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    (src / "settings.json").write_text("mutable\n")
    (src / "retired.txt").write_text("retired\n")
    dst = tmp_path / "dst"
    assert _run_managed(tmp_path, shim_text, _managed_call(src, dst)).returncode == 0
    (src / "settings.json").unlink()
    (src / "retired.txt").unlink()

    result = _run_managed(tmp_path, shim_text, _managed_call(src, dst, "fixture", "settings.json"))

    assert result.returncode == 0, result.stderr
    assert (dst / "settings.json").read_text() == "mutable\n"
    assert not (dst / "retired.txt").exists()


@pytest.mark.parametrize("preserved", ["", "/absolute", ".", "..", "a/", "a//b", "a/./b", "a/../b"])
def test_install_config_dir_rejects_invalid_preserved_paths(tmp_path: Path, shim_text: str, preserved: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"

    result = _run_managed(tmp_path, shim_text, _managed_call(src, dst, "fixture", preserved))

    assert result.returncode != 0
    assert "invalid preserved path" in result.stderr
    assert not dst.exists()


def test_install_config_dir_rejects_duplicate_and_inventory_preserved_paths(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    calls = (
        _managed_call(src, dst, "fixture", "released.json", "released.json"),
        _managed_call(src, dst, "fixture", "a.txt"),
        _managed_call(src, dst, "fixture", "nested dir"),
    )

    for call in calls:
        result = _run_managed(tmp_path, shim_text, call)
        assert result.returncode != 0
        assert "preserved path" in result.stderr
        assert not dst.exists()


def test_install_config_dir_two_argument_overlay_never_uses_managed_state(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    (dst / "retired.txt").parent.mkdir(parents=True)
    (dst / "retired.txt").write_text("keep\n")
    state = tmp_path / "state"
    manifest = _managed_manifest(state, "fixture")
    manifest.parent.mkdir(parents=True)
    manifest.symlink_to(tmp_path / "missing")
    script = tmp_path / "overlay.sh"
    script.write_text(f"set -euo pipefail\n{shim_text}\n{_call(src, dst)}\n")
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=os_module.environ | {"XDG_STATE_HOME": str(state)})
    assert result.returncode == 0, result.stderr
    assert (dst / "retired.txt").read_text() == "keep\n"
    assert manifest.is_symlink()


def test_install_config_dir_managed_identity_and_destination_binding_fail_closed(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    state = tmp_path / "state"
    for identity in ("", ".", "..", "Upper", "a/b", r"a\\b", "a b", "a\nb", "-a", "_a", "a" * 65):
        dst = tmp_path / f"bad-{len(identity)}"
        result = _run_managed(tmp_path, shim_text, _managed_call(src, dst, identity))
        assert result.returncode != 0
        assert "invalid managed identity" in result.stderr
        assert not dst.exists()
        assert not _managed_manifest(state, identity).exists()
    first = tmp_path / "dst-one"
    second = tmp_path / "dst-two"
    assert _run_managed(tmp_path, shim_text, _managed_call(src, first)).returncode == 0
    manifest = _managed_manifest(state, "fixture")
    before_tree, before_manifest = _tree(first), manifest.read_bytes()
    result = _run_managed(tmp_path, shim_text, _managed_call(src, second))
    assert result.returncode != 0
    assert "destination mismatch" in result.stderr
    assert not second.exists()
    assert _tree(first) == before_tree
    assert manifest.read_bytes() == before_manifest


def test_install_config_dir_managed_manifest_schema_and_paths_fail_before_mutation(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    assert _run_managed(tmp_path, shim_text, _managed_call(src, dst)).returncode == 0
    manifest = _managed_manifest(tmp_path / "state", "fixture")
    good = [b"dotgen-install-config-dir-v1", os_module.fsencode(str(dst)), b"a.txt"]
    malformed = (
        [b"bad", good[1]],
        [b"dotgen-install-config-dir-v2", good[1]],
        [good[0]],
        [good[0], b"/other"],
        [good[0], good[1], b"a.txt", b"a.txt"],
        [good[0], good[1], b"/absolute"],
        [good[0], good[1], b""],
        [good[0], good[1], b"."],
        [good[0], good[1], b"a/../b"],
        [good[0], good[1], b"a//b"],
    )
    for records in malformed:
        (dst / "sentinel").write_text("keep\n")
        _write_manifest(manifest, list(records))
        before_tree, before_manifest = _tree(dst), manifest.read_bytes()
        result = _run_managed(tmp_path, shim_text, _managed_call(src, dst))
        assert result.returncode != 0
        assert "install_config_dir:" in result.stderr
        assert _tree(dst) == before_tree
        assert manifest.read_bytes() == before_manifest
    _write_manifest(manifest, good, trailing_nul=False)
    before_tree, before_manifest = _tree(dst), manifest.read_bytes()
    result = _run_managed(tmp_path, shim_text, _managed_call(src, dst))
    assert result.returncode != 0
    assert result.stdout == ""
    assert "invalid manifest schema" in result.stderr
    assert _tree(dst) == before_tree
    assert manifest.read_bytes() == before_manifest


def test_install_config_dir_managed_normalizes_destination_componentwise(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    raw_dst = tmp_path / "physical root" / "discard" / ".." / "managed dir"
    expected_dst = tmp_path / "physical root" / "managed dir"
    deploy = _run_managed(tmp_path, shim_text, _managed_call(src, raw_dst))
    assert deploy.returncode == 0, deploy.stderr
    assert (expected_dst / "a.txt").read_bytes() == (src / "a.txt").read_bytes()
    assert not (tmp_path / "physical root" / "discard").exists()
    manifest = _managed_manifest(tmp_path / "state", "fixture")
    assert _manifest_records(manifest)[:2] == [
        b"dotgen-install-config-dir-v1",
        os_module.fsencode(str(expected_dst)),
    ]


def test_install_config_dir_managed_normalized_destination_refuses_symlink_ancestor(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    raw_dst = linked_parent / "discard" / ".." / "managed"
    manifest = _managed_manifest(tmp_path / "state", "symlink-ancestor")
    result = _run_managed(tmp_path, shim_text, _managed_call(src, raw_dst, "symlink-ancestor"))
    assert result.returncode != 0
    assert result.stdout == ""
    assert "symlink destination ancestor" in result.stderr
    assert str(linked_parent) in result.stderr
    assert not (real_parent / "managed").exists()
    assert not manifest.exists()


def test_install_config_dir_managed_unusual_filename_round_trip(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    weird = "delimiter\n\t\\*?["
    (src / weird).write_text("weird\n")
    dst = tmp_path / "dst"
    assert _run_managed(tmp_path, shim_text, _managed_call(src, dst)).returncode == 0
    assert (dst / weird).read_text() == "weird\n"
    manifest = _managed_manifest(tmp_path / "state", "fixture")
    assert os_module.fsencode(weird) in _manifest_records(manifest)
    (src / weird).unlink()
    assert _run_managed(tmp_path, shim_text, _managed_call(src, dst)).returncode == 0
    assert not (dst / weird).exists()
    assert (dst / "nested dir").is_dir()


def test_install_config_dir_managed_symlink_and_type_conflicts_are_atomic(tmp_path: Path, shim_text: str) -> None:
    def assert_conflict(prepare: Callable[[Path, Path], None]) -> None:
        root = tmp_path / f"case-{len(list(tmp_path.iterdir()))}"
        src = _vendor_src(root)
        dst = root / "dst"
        assert _run_managed(root, shim_text, _managed_call(src, dst)).returncode == 0
        manifest = _managed_manifest(root / "state", "fixture")
        prepare(src, dst)
        before_tree, before_manifest = _tree(dst), manifest.read_bytes()
        result = _run_managed(root, shim_text, _managed_call(src, dst))
        assert result.returncode != 0
        assert "install_config_dir:" in result.stderr
        assert _tree(dst) == before_tree
        assert manifest.read_bytes() == before_manifest

    def file_over_dir(src: Path, dst: Path) -> None:
        (dst / "a.txt").unlink()
        (dst / "a.txt").mkdir()

    def dir_over_file(src: Path, dst: Path) -> None:
        shutil.rmtree(dst / "nested dir")
        (dst / "nested dir").write_text("file\n")

    def retired_over_dir(src: Path, dst: Path) -> None:
        (src / "a.txt").unlink()
        (dst / "a.txt").unlink()
        (dst / "a.txt").mkdir()

    for prepare in (file_over_dir, dir_over_file, retired_over_dir):
        assert_conflict(prepare)
    src = _vendor_src(tmp_path / "source-symlink")
    (src / "link").symlink_to("a.txt")
    result = _run_managed(tmp_path / "source-symlink", shim_text, _managed_call(src, tmp_path / "source-symlink" / "dst"))
    assert result.returncode != 0
    assert "source contains non-file entry" in result.stderr


def test_install_config_dir_managed_copy_interruption_reruns_from_old_manifest(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    (dst / "unmanaged" / "empty").mkdir(parents=True)
    (dst / "unmanaged.txt").write_text("keep\n")
    assert _run_managed(tmp_path, shim_text, _managed_call(src, dst)).returncode == 0
    (src / "a.txt").unlink()
    (src / "run.sh").write_text("changed\n")
    (src / "new.txt").write_text("new\n")
    manifest = _managed_manifest(tmp_path / "state", "fixture")
    old_manifest = manifest.read_bytes()
    result = _run_managed(tmp_path, shim_text, _managed_call(src, dst), prelude="cp() { return 71; }")
    assert result.returncode != 0
    assert manifest.read_bytes() == old_manifest
    rerun = _run_managed(tmp_path, shim_text, _managed_call(src, dst))
    assert rerun.returncode == 0, rerun.stderr
    assert not (dst / "a.txt").exists()
    assert (dst / "run.sh").read_text() == "changed\n"
    assert (dst / "new.txt").read_text() == "new\n"
    assert (dst / "unmanaged.txt").read_text() == "keep\n"
    assert (dst / "unmanaged" / "empty").is_dir()
    assert b"new.txt" in _manifest_records(manifest)


def _debian_shim_at(tmp_path: Path) -> str:
    shim = OSShim(OS.DEBIAN).render()
    return shim.replace("/etc/apt/keyrings", str(tmp_path / "keyrings")).replace("/etc/apt/sources.list.d", str(tmp_path / "sources"))


def _run_debian_harness(
    tmp_path: Path,
    call: str,
    *,
    installed: str = "",
    gpg_ok: bool = True,
    curl_ok: bool = True,
    mask_bad: str = "",
) -> subprocess.CompletedProcess[str]:
    fake = tmp_path / "bin"
    shutil.rmtree(fake, ignore_errors=True)
    fake.mkdir()
    (tmp_path / "key.txt").write_text("-----BEGIN PGP PUBLIC KEY BLOCK-----\nfixture\n")
    dispatcher = fake / "command"
    dispatcher.write_text(
        """#!/usr/bin/env bash
set -u
case "$(basename "$0")" in
sudo)
  printf 'sudo' >> "$STATE/commands"; for arg in "$@"; do printf ' <%s>' "$arg" >> "$STATE/commands"; done; printf '\\n' >> "$STATE/commands"
  while [[ "${1:-}" = *=* ]]; do shift; done; "$@" ;;
curl)
  printf 'curl %s\\n' "$*" >> "$STATE/commands"
  [ "$CURL_OK" = 1 ] || exit 127
  while [ "$#" -gt 0 ]; do [ "$1" = -o ] && { cp "$KEY_FIXTURE" "$2"; exit 0; }; shift; done; exit 1 ;;
gpg) printf 'gpg %s\\n' "$*" >> "$STATE/commands"; [ "$GPG_OK" = 1 ] ;;
apt-get) printf "%s\n" "$*" >> "$STATE/apt" ;;
systemctl)
  case "$1" in
  is-enabled) cat "$STATE/$2.enabled" 2>/dev/null || echo enabled ;;
  is-active) unit="${@: -1}"; [ "$(cat "$STATE/$unit.active" 2>/dev/null || echo inactive)" = active ] ;;
  mask)
    shift 2
    for unit in "$@"; do echo masked > "$STATE/$unit.enabled"; echo inactive > "$STATE/$unit.active"; done
    if [ "$MASK_BAD" = enabled ]; then echo enabled > "$STATE/${@: -1}.enabled"; fi
    if [ "$MASK_BAD" = active ]; then echo active > "$STATE/${@: -1}.active"; fi
    ;;
  esac ;;
esac
"""
    )
    dispatcher.chmod(0o755)
    for name in ("sudo", "curl", "gpg", "systemctl", "apt-get"):
        (fake / name).symlink_to("command")
    script = tmp_path / "run.sh"
    script.write_text("set -euo pipefail\n" + _debian_shim_at(tmp_path) + "\n" + 'pkg_installed() { [[ " $INSTALLED " == *" $1 "* ]]; }\n' + call + "\n")
    env = {
        **os_module.environ,
        "PATH": f"{fake}:{os_module.environ['PATH']}",
        "TMPDIR": str(tmp_path / "temps"),
        "KEY_FIXTURE": str(tmp_path / "key.txt"),
        "GPG_OK": "1" if gpg_ok else "0",
        "CURL_OK": "1" if curl_ok else "0",
        "MASK_BAD": mask_bad,
        "STATE": str(tmp_path / "state"),
        "INSTALLED": installed,
    }
    (tmp_path / "temps").mkdir(exist_ok=True)
    (tmp_path / "state").mkdir(exist_ok=True)
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)


_DEB822 = "Types: deb\nURIs: https://example.test\nSuites: trixie\nComponents: stable\nArchitectures: amd64\nSigned-By: {key}\n"


@pytest.mark.parametrize("key_state, source_state", [("absent", "absent"), ("drift", "equal"), ("equal", "drift"), ("drift", "drift"), ("equal", "equal")])
def test_deb822_repository_status_matrix_is_independent_and_atomic(tmp_path: Path, key_state: str, source_state: str) -> None:
    key = tmp_path / "keyrings/docker.asc"
    source = tmp_path / "sources/docker.sources"
    key.parent.mkdir()
    source.parent.mkdir()
    stanza = _DEB822.format(key=key)
    fixture = "-----BEGIN PGP PUBLIC KEY BLOCK-----\nfixture\n"
    for path, state, content in ((key, key_state, fixture), (source, source_state, stanza)):
        if state != "absent":
            path.write_text(content if state == "equal" else "drift\n")
            os_module.utime(path, ns=(1_000_000_000, 1_000_000_000))
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (key, source) if path.exists()}
    result = _run_debian_harness(tmp_path, f'add_repo apt-deb822 docker "{stanza}" https://key.test')
    assert result.returncode == 0, result.stderr
    assert key.read_text() == fixture and source.read_text() == stanza
    assert key.stat().st_mode & 0o777 == 0o644 and source.stat().st_mode & 0o777 == 0o644
    commands = (tmp_path / "state/commands").read_text()
    for path, state in ((key, key_state), (source, source_state)):
        if state == "equal":
            assert path.stat().st_mtime_ns == before[path][1]
            assert f"<{path}>" not in commands
        else:
            assert f"mv> <-f> <{path.parent}/.docker.{path.suffix[1:]}." in commands
    assert not list((tmp_path / "temps").iterdir())


@pytest.mark.parametrize(
    "identifier, stanza",
    [
        ("docker", ""),
        ("docker", "Types: deb\n"),
        ("docker", "Types: deb\n\nURIs: x"),
        ("docker", "Types: deb\n Signed-By: x"),
        ("docker", "Types: deb\r\nURIs: x"),
        ("Docker/unsafe", "Types: deb"),
    ],
)
def test_deb822_rejects_malformed_source_and_cleans_temps(tmp_path: Path, identifier: str, stanza: str) -> None:
    result = _run_debian_harness(tmp_path, f'add_repo apt-deb822 {identifier} "{stanza}" https://key.test')
    assert result.returncode != 0
    assert not list((tmp_path / "temps").iterdir())
    assert not (tmp_path / "keyrings/docker.asc").exists()
    assert not (tmp_path / "sources/docker.sources").exists()


@pytest.mark.parametrize("legacy_name", ["docker.list", "docker.gpg"])
def test_deb822_rejects_legacy_collisions_before_privileged_writes(tmp_path: Path, legacy_name: str) -> None:
    parent = tmp_path / ("sources" if legacy_name.endswith(".list") else "keyrings")
    parent.mkdir()
    legacy = parent / legacy_name
    legacy.write_text("administrator owned")
    stanza = _DEB822.format(key=tmp_path / "keyrings/docker.asc")
    result = _run_debian_harness(tmp_path, f'add_repo apt-deb822 docker "{stanza}" https://key.test')
    assert result.returncode != 0 and legacy.read_text() == "administrator owned"
    assert not (tmp_path / "state/commands").exists()


@pytest.mark.parametrize(
    "stanza",
    [
        "Types: deb\nTypes: deb\nURIs: https://example.test\nSuites: trixie\nComponents: stable\nArchitectures: amd64\nSigned-By: {key}\n",
        "Types: deb\nURIs: https://example.test\nSuites: trixie\nComponents: stable\nArchitectures: amd64\nSigned-By: /wrong.asc\n",
    ],
)
def test_deb822_rejects_duplicate_and_wrong_signed_by_without_writes(tmp_path: Path, stanza: str) -> None:
    result = _run_debian_harness(tmp_path, f'add_repo apt-deb822 docker "{stanza.format(key=tmp_path / "keyrings/docker.asc")}" https://key.test')
    assert result.returncode != 0
    assert not (tmp_path / "state/commands").exists()


def test_deb822_rejects_unsafe_target_without_writes(tmp_path: Path) -> None:
    target = tmp_path / "keyrings/docker.asc"
    target.parent.mkdir()
    target.symlink_to(tmp_path / "outside")
    stanza = _DEB822.format(key=target)
    result = _run_debian_harness(tmp_path, f'add_repo apt-deb822 docker "{stanza}" https://key.test')
    assert result.returncode != 0
    assert target.is_symlink() and not (tmp_path / "state/commands").exists()


@pytest.mark.parametrize("gpg_ok, curl_ok", [(False, True), (True, False)])
def test_deb822_bad_or_unavailable_key_cleans_temps(tmp_path: Path, gpg_ok: bool, curl_ok: bool) -> None:
    stanza = _DEB822.format(key=tmp_path / "keyrings/docker.asc")
    result = _run_debian_harness(tmp_path, f'add_repo apt-deb822 docker "{stanza}" https://key.test', gpg_ok=gpg_ok, curl_ok=curl_ok)
    assert result.returncode != 0
    assert not list((tmp_path / "temps").iterdir())


def test_remove_packages_uses_one_exact_batched_deploy_transaction(tmp_path: Path) -> None:
    result = _run_debian_harness(tmp_path, "remove_packages absent second present", installed="present second")
    assert result.returncode == 0, result.stderr
    commands = (tmp_path / "state/commands").read_text()
    assert commands.splitlines() == ["sudo <DEBIAN_FRONTEND=noninteractive> <apt-get> <remove> <-y> <second> <present>"]
    assert "purge" not in commands and "/var/lib" not in commands
    before = commands
    result = _run_debian_harness(tmp_path, "remove_packages absent", installed="present")
    assert result.returncode == 0 and (tmp_path / "state/commands").read_text() == before


def test_service_mask_logs_state_and_verifies(tmp_path: Path) -> None:
    result = _run_debian_harness(tmp_path, "service_mask docker.service docker.socket")
    assert result.returncode == 0, result.stderr
    state = tmp_path / "state"
    assert (state / "docker.service.enabled").read_text().strip() == "masked"
    assert (state / "docker.service.active").read_text().strip() == "inactive"
    assert (state / "commands").read_text().splitlines() == ["sudo <systemctl> <mask> <--now> <docker.service> <docker.socket>"]


@pytest.mark.parametrize("bad", ["enabled", "active"])
def test_service_mask_rejects_failed_post_mask_verification(tmp_path: Path, bad: str) -> None:
    result = _run_debian_harness(tmp_path, "service_mask docker.service docker.socket", mask_bad=bad)
    assert result.returncode != 0
    assert "docker.socket" in result.stderr


def test_macos_rejects_debian_helpers(tmp_path: Path) -> None:
    macos = OSShim(OS.MACOS).render()
    for call in (
        "add_repo apt-deb822 docker source key",
        "remove_packages docker.io",
        "service_mask docker.service",
    ):
        script = tmp_path / "run.sh"
        script.write_text(f"set -euo pipefail\n{macos}\n{call}\n")
        assert subprocess.run(["bash", str(script)], capture_output=True, text=True).returncode != 0
