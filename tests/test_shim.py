import os as os_module
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from dotgen.shim import SHIM_FUNCTIONS, OSShim
from dotgen.types import OS

_DEF_RE = re.compile(r"^([a-z_][a-z_0-9]*)\(\) \{", re.MULTILINE)


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


_MODE_AWARE = (
    "install_config",
    "install_config_dir",
    "link_file",
    "install_script",
    "install_package",
    "remove_packages",
    "install_cask",
    "add_repo",
    "update_pkg_index",
    "service_enable",
    "service_mask",
    "download_bin",
    "download_tar_bin",
)


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


_SIDE_EFFECT_TOKENS = (
    "apt-get",
    "brew ",
    "curl ",
    "sudo ",
    "install -",
    "ln -",
    "tee ",
    "tar ",
    "systemctl ",
)


def test_mode_aware_helpers_branch_on_diff(shim_text: str) -> None:
    for fn in _MODE_AWARE:
        body = _function_body(shim_text, fn)
        if '"$DOTGEN_MODE" = diff' in body:
            continue
        # OK if this OS's body is a stub (e.g. install_cask on linux)
        assert not any(t in body for t in _SIDE_EFFECT_TOKENS), f"{fn} has side effects without a diff-mode branch:\n{body}"


def _run_shim_fn(tmp_path: Path, shim_text: str, mode: str, call: str) -> str:
    script = tmp_path / "run.sh"
    script.write_text(f"{shim_text}\nDOTGEN_MODE={mode}\n{call}\n")
    return subprocess.check_output(["bash", str(script)]).decode()


def test_component_begin_prints_in_diff_mode(tmp_path: Path, shim_text: str) -> None:
    out = _run_shim_fn(tmp_path, shim_text, "diff", "component_begin aws")
    assert out == "--- aws ---\n"


def test_component_begin_silent_in_deploy_mode(tmp_path: Path, shim_text: str) -> None:
    out = _run_shim_fn(tmp_path, shim_text, "deploy", "component_begin aws")
    # In deploy mode it might print a progress line, which is fine
    assert "---" not in out


def _macos_shim() -> str:
    return OSShim(OS.MACOS).render()


def _write_secrets(tmp_path: Path, body: str) -> None:
    (tmp_path / "dotgen").mkdir()
    (tmp_path / "dotgen" / "secrets.env").write_text(body)


def _run_template(tmp_path: Path, mode: str, src: str, vars_list: str, *, secrets: str) -> subprocess.CompletedProcess[str]:
    _write_secrets(tmp_path, secrets)
    src_path = tmp_path / "src"
    src_path.write_text(src)
    dst_path = tmp_path / "dst"
    script = tmp_path / "run.sh"
    script.write_text(f"{_macos_shim()}\nexport XDG_CONFIG_HOME={tmp_path}\nexport DOTGEN_MODE={mode}\ninstall_config_template {src_path} {dst_path} '{vars_list}'\n")
    return subprocess.run(["bash", str(script)], capture_output=True, text=True)


def test_install_config_template_renders(tmp_path: Path) -> None:
    res = _run_template(
        tmp_path,
        mode="deploy",
        src="name=${GIT_USER_NAME}\nemail=${GIT_USER_EMAIL}\n",
        vars_list="GIT_USER_NAME GIT_USER_EMAIL",
        secrets='GIT_USER_NAME="Alice"\nGIT_USER_EMAIL="a@example.com"\n',
    )
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "dst").read_text() == "name=Alice\nemail=a@example.com\n"


def test_install_config_template_missing_secrets(tmp_path: Path) -> None:
    res = _run_template(
        tmp_path,
        mode="deploy",
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
        mode="deploy",
        src="name=${GIT_USER_NAME}\npath=$PATH\n",
        vars_list="GIT_USER_NAME",
        secrets='GIT_USER_NAME="Alice"\n',
    )
    assert res.returncode == 0, res.stderr
    out = (tmp_path / "dst").read_text()
    assert "Alice" in out
    assert "$PATH" in out


def test_install_config_template_diff_mode_does_not_write(tmp_path: Path) -> None:
    res = _run_template(
        tmp_path,
        mode="diff",
        src="name=${GIT_USER_NAME}\n",
        vars_list="GIT_USER_NAME",
        secrets='GIT_USER_NAME="Alice"\n',
    )
    assert res.returncode == 0, res.stderr
    assert "(templated)" in res.stdout
    assert not (tmp_path / "dst").exists()


def test_install_config_template_missing_secrets_file(tmp_path: Path) -> None:
    src_path = tmp_path / "src"
    src_path.write_text("name=${GIT_USER_NAME}\n")
    dst_path = tmp_path / "dst"
    script = tmp_path / "run.sh"
    script.write_text(f"{_macos_shim()}\nexport XDG_CONFIG_HOME={tmp_path}\nexport DOTGEN_MODE=deploy\ninstall_config_template {src_path} {dst_path} 'GIT_USER_NAME'\n")
    res = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert res.returncode != 0
    assert "missing secrets file" in res.stderr
    assert not dst_path.exists()


def test_load_secrets_idempotent(tmp_path: Path) -> None:
    _write_secrets(tmp_path, 'COUNTER="$((${COUNTER:-0}+1))"\n')
    script = tmp_path / "run.sh"
    script.write_text(f'{_macos_shim()}\nexport XDG_CONFIG_HOME={tmp_path}\nexport DOTGEN_MODE=deploy\nload_secrets\nload_secrets\nprintf "%s" "$COUNTER"\n')
    res = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "1"


def test_debian_shim_uses_sudo_for_package_install(tmp_path: Path) -> None:
    shim = OSShim(OS.DEBIAN).render()
    script = tmp_path / "run.sh"
    script.write_text(
        f"""{shim}
DOTGEN_MODE=deploy
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


def test_debian_remove_packages_and_macos_stubs(tmp_path: Path) -> None:
    debian = OSShim(OS.DEBIAN).render()
    script = tmp_path / "run.sh"
    script.write_text(
        f"""set -euo pipefail
{debian}
DOTGEN_MODE=diff
pkg_installed() {{ [ "$1" = installed ]; }}
remove_packages absent installed
"""
    )
    res = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "- REMOVE pkg installed\n"
    macos = OSShim(OS.MACOS).render()
    assert "debian only" in _function_body(macos, "remove_packages")
    assert "debian only" in _function_body(macos, "service_mask")


def test_npm_install_activates_fnm_in_its_component_subshell() -> None:
    body = _function_body(OSShim(OS.DEBIAN).render(), "install_npm_global")
    assert 'fnm_bin="$HOME/.local/share/fnm/fnm"' in body
    assert 'eval "$("$fnm_bin" env --shell bash)"' in body
    assert 'error "npm unavailable; node_fnm must run before npm installs"' in body


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


def test_install_config_dir_deploy_overlays_contents(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    (dst / "git-like").mkdir(parents=True)
    (dst / "git-like" / "HEAD").write_text("ref\n")
    (dst / "unmanaged.txt").write_text("keep\n")

    out = _run_shim_fn(tmp_path, shim_text, "deploy", _call(src, dst))

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
    _run_shim_fn(tmp_path, shim_text, "deploy", _call(src, dst))
    first = _tree(dst)

    out = _run_shim_fn(tmp_path, shim_text, "deploy", _call(src, dst))

    assert out == ""
    assert _tree(dst) == first


def test_install_config_dir_diff_reports_copy_when_absent(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"

    out = _run_shim_fn(tmp_path, shim_text, "diff", _call(src, dst))

    assert out == f"+ COPY   {dst}\n"
    assert not dst.exists()


def test_install_config_dir_diff_silent_when_bytes_equal(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    _run_shim_fn(tmp_path, shim_text, "deploy", _call(src, dst))

    assert _run_shim_fn(tmp_path, shim_text, "diff", _call(src, dst)) == ""


def test_install_config_dir_diff_reports_sync_and_leaves_target_alone(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    _run_shim_fn(tmp_path, shim_text, "deploy", _call(src, dst))
    (dst / "nested dir" / "b file.txt").write_text("drifted\n")
    before = _tree(dst)

    out = _run_shim_fn(tmp_path, shim_text, "diff", _call(src, dst))

    assert out == f"~ SYNC   {dst}\n"
    assert _tree(dst) == before


def test_install_config_dir_diff_ignores_mode_only_difference(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    _run_shim_fn(tmp_path, shim_text, "deploy", _call(src, dst))
    (dst / "run.sh").chmod(0o644)

    assert _run_shim_fn(tmp_path, shim_text, "diff", _call(src, dst)) == ""
    assert not (dst / "run.sh").stat().st_mode & 0o111


def test_install_config_dir_diff_ignores_unmanaged_target_files(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    _run_shim_fn(tmp_path, shim_text, "deploy", _call(src, dst))
    (dst / "extra.txt").write_text("extra\n")
    (dst / "git-like").mkdir()
    (dst / "git-like" / "HEAD").write_text("ref\n")

    assert _run_shim_fn(tmp_path, shim_text, "diff", _call(src, dst)) == ""


def test_install_config_dir_diff_reports_sync_when_shipped_file_missing(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    _run_shim_fn(tmp_path, shim_text, "deploy", _call(src, dst))
    (dst / "a.txt").unlink()

    out = _run_shim_fn(tmp_path, shim_text, "diff", _call(src, dst))

    assert out == f"~ SYNC   {dst}\n"
    assert not (dst / "a.txt").exists()


def _run_shim_checked(tmp_path: Path, shim_text: str, mode: str, call: str) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "run.sh"
    script.write_text(f"set -euo pipefail\n{shim_text}\nDOTGEN_MODE={mode}\n{call}\n")
    return subprocess.run(["bash", str(script)], capture_output=True, text=True)


def test_install_config_dir_deploy_refuses_file_over_target_directory(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    (dst / "a.txt").mkdir(parents=True)
    (dst / "a.txt" / "unmanaged.txt").write_text("keep\n")

    res = _run_shim_checked(tmp_path, shim_text, "deploy", _call(src, dst))

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

    res = _run_shim_checked(tmp_path, shim_text, "deploy", _call(src, dst))

    assert res.returncode != 0
    assert f"{dst}/nested dir" in res.stderr
    assert (dst / "nested dir").read_text() == "i am a file\n"
    assert not (dst / "a.txt").exists()


def test_install_config_dir_diff_reports_sync_on_type_mismatch(tmp_path: Path, shim_text: str) -> None:
    src = _vendor_src(tmp_path)
    dst = tmp_path / "dst"
    (dst / "a.txt").mkdir(parents=True)
    before = _tree(dst)

    res = _run_shim_checked(tmp_path, shim_text, "diff", _call(src, dst))

    assert res.returncode == 0
    assert res.stdout == f"~ SYNC   {dst}\n"
    assert f"{dst}/a.txt" in res.stderr
    assert _tree(dst) == before


def test_install_config_dir_fails_on_missing_source(tmp_path: Path, shim_text: str) -> None:
    src = tmp_path / "nope"
    dst = tmp_path / "dst"

    for mode in ("deploy", "diff"):
        res = _run_shim_checked(tmp_path, shim_text, mode, _call(src, dst))
        assert res.returncode != 0, mode
        assert "missing source directory" in res.stderr
        assert not dst.exists()


def test_install_config_dir_handles_empty_source(tmp_path: Path, shim_text: str) -> None:
    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"

    assert _run_shim_checked(tmp_path, shim_text, "diff", _call(src, dst)).stdout == f"+ COPY   {dst}\n"
    assert not dst.exists()

    deployed = _run_shim_checked(tmp_path, shim_text, "deploy", _call(src, dst))
    assert deployed.returncode == 0, deployed.stderr
    assert dst.is_dir()

    assert _run_shim_checked(tmp_path, shim_text, "diff", _call(src, dst)).stdout == ""
    assert _run_shim_checked(tmp_path, shim_text, "deploy", _call(src, dst)).stdout == ""


def _debian_shim_at(tmp_path: Path) -> str:
    shim = OSShim(OS.DEBIAN).render()
    return shim.replace("/etc/apt/keyrings", str(tmp_path / "keyrings")).replace("/etc/apt/sources.list.d", str(tmp_path / "sources"))


def _run_debian_harness(
    tmp_path: Path,
    mode: str,
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
    script.write_text("set -euo pipefail\n" + _debian_shim_at(tmp_path) + "\nDOTGEN_MODE=" + mode + '\npkg_installed() { [[ " $INSTALLED " == *" $1 "* ]]; }\n' + call + "\n")
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


@pytest.mark.parametrize("mode", ["diff", "deploy"])
@pytest.mark.parametrize("key_state, source_state", [("absent", "absent"), ("drift", "equal"), ("equal", "drift"), ("drift", "drift"), ("equal", "equal")])
def test_deb822_repository_status_matrix_is_independent_and_atomic(tmp_path: Path, mode: str, key_state: str, source_state: str) -> None:
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
    result = _run_debian_harness(tmp_path, mode, f'add_repo apt-deb822 docker "{stanza}" https://key.test')
    assert result.returncode == 0, result.stderr
    if mode == "diff":
        expected: list[str] = []
        for label, path, state in (("KEY", key, key_state), ("SOURCE", source, source_state)):
            if state != "equal":
                verb = "ADD" if state == "absent" else "CHANGE"
                expected.append(f"{'+' if verb == 'ADD' else '~'} {verb} REPO {label} {path}")
        assert result.stdout.splitlines() == expected
        assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (key, source) if path.exists()} == before
        assert not (tmp_path / "state/commands").exists() or "sudo" not in (tmp_path / "state/commands").read_text()
    else:
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
    result = _run_debian_harness(tmp_path, "deploy", f'add_repo apt-deb822 {identifier} "{stanza}" https://key.test')
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
    result = _run_debian_harness(tmp_path, "deploy", f'add_repo apt-deb822 docker "{stanza}" https://key.test')
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
    result = _run_debian_harness(tmp_path, "deploy", f'add_repo apt-deb822 docker "{stanza.format(key=tmp_path / "keyrings/docker.asc")}" https://key.test')
    assert result.returncode != 0
    assert not (tmp_path / "state/commands").exists()


def test_deb822_rejects_unsafe_target_without_writes(tmp_path: Path) -> None:
    target = tmp_path / "keyrings/docker.asc"
    target.parent.mkdir()
    target.symlink_to(tmp_path / "outside")
    stanza = _DEB822.format(key=target)
    result = _run_debian_harness(tmp_path, "deploy", f'add_repo apt-deb822 docker "{stanza}" https://key.test')
    assert result.returncode != 0
    assert target.is_symlink() and not (tmp_path / "state/commands").exists()


@pytest.mark.parametrize("gpg_ok, curl_ok", [(False, True), (True, False)])
def test_deb822_bad_or_unavailable_key_cleans_temps(tmp_path: Path, gpg_ok: bool, curl_ok: bool) -> None:
    stanza = _DEB822.format(key=tmp_path / "keyrings/docker.asc")
    result = _run_debian_harness(tmp_path, "diff", f'add_repo apt-deb822 docker "{stanza}" https://key.test', gpg_ok=gpg_ok, curl_ok=curl_ok)
    assert result.returncode != 0
    assert not list((tmp_path / "temps").iterdir())


def test_remove_packages_uses_one_exact_batched_deploy_transaction(tmp_path: Path) -> None:
    result = _run_debian_harness(tmp_path, "diff", "remove_packages absent second present", installed="present second")
    assert result.returncode == 0 and result.stdout.splitlines() == ["- REMOVE pkg second", "- REMOVE pkg present"]
    assert not (tmp_path / "state/commands").exists()
    result = _run_debian_harness(tmp_path, "deploy", "remove_packages absent second present", installed="present second")
    assert result.returncode == 0, result.stderr
    commands = (tmp_path / "state/commands").read_text()
    assert commands.splitlines() == ["sudo <DEBIAN_FRONTEND=noninteractive> <apt-get> <remove> <-y> <second> <present>"]
    assert "purge" not in commands and "/var/lib" not in commands
    before = commands
    result = _run_debian_harness(tmp_path, "deploy", "remove_packages absent", installed="present")
    assert result.returncode == 0 and (tmp_path / "state/commands").read_text() == before


def test_service_mask_logs_state_verifies_and_diff_is_immutable(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "docker.socket.enabled").write_text("masked\n")
    (state / "docker.socket.active").write_text("inactive\n")
    result = _run_debian_harness(tmp_path, "diff", "service_mask docker.service docker.socket")
    assert result.returncode == 0 and result.stdout == "~ MASK service docker.service\n"
    assert (state / "docker.socket.enabled").read_text() == "masked\n"
    assert not (state / "commands").exists()
    result = _run_debian_harness(tmp_path, "deploy", "service_mask docker.service docker.socket")
    assert result.returncode == 0, result.stderr
    assert (state / "docker.service.enabled").read_text().strip() == "masked"
    assert (state / "docker.service.active").read_text().strip() == "inactive"
    assert (state / "commands").read_text().splitlines() == ["sudo <systemctl> <mask> <--now> <docker.service> <docker.socket>"]


@pytest.mark.parametrize("bad", ["enabled", "active"])
def test_service_mask_rejects_failed_post_mask_verification(tmp_path: Path, bad: str) -> None:
    result = _run_debian_harness(tmp_path, "deploy", "service_mask docker.service docker.socket", mask_bad=bad)
    assert result.returncode != 0
    assert "docker.socket" in result.stderr


def test_macos_rejects_new_debian_helpers_and_legacy_paths_regressions(tmp_path: Path) -> None:
    macos = OSShim(OS.MACOS).render()
    calls = (
        ("diff", "add_repo apt-deb822 docker source key"),
        ("deploy", "add_repo apt-deb822 docker source key"),
        ("deploy", "remove_packages docker.io"),
        ("deploy", "service_mask docker.service"),
    )
    for mode, call in calls:
        script = tmp_path / "run.sh"
        script.write_text(f"set -euo pipefail\n{macos}\nDOTGEN_MODE={mode}\n{call}\n")
        assert subprocess.run(["bash", str(script)], capture_output=True, text=True).returncode != 0
    assert _run_shim_fn(tmp_path, macos, "diff", "add_repo tap homebrew/core") == "+ ADD REPO homebrew/core (tap)\n"
    debian = OSShim(OS.DEBIAN).render()
    assert _run_shim_fn(tmp_path, debian, "diff", "add_repo apt example 'deb https://example.test stable main' https://key.test") == "+ ADD REPO example (apt)\n"
