import re
import subprocess
import textwrap

import pytest

from dotgen.shim import SHIM_FUNCTIONS, OSShim
from dotgen.types import OS

_DEF_RE = re.compile(r"^([a-z_][a-z_0-9]*)\(\) \{", re.MULTILINE)


@pytest.fixture(params=list(OS), ids=[o.value for o in OS])
def shim_text(request: pytest.FixtureRequest) -> str:
    return OSShim(request.param).render()


def test_shim_is_bash_clean(tmp_path, shim_text: str) -> None:
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
    "link_file",
    "install_script",
    "install_package",
    "install_cask",
    "add_repo",
    "update_pkg_index",
    "service_enable",
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


def _run_shim_fn(tmp_path, shim_text: str, mode: str, call: str) -> str:
    script = tmp_path / "run.sh"
    script.write_text(f"{shim_text}\nDOTGEN_MODE={mode}\n{call}\n")
    return subprocess.check_output(["bash", str(script)]).decode()


def test_component_begin_prints_in_diff_mode(tmp_path, shim_text: str) -> None:
    out = _run_shim_fn(tmp_path, shim_text, "diff", "component_begin aws")
    assert out == "--- aws ---\n"


def test_component_begin_silent_in_deploy_mode(tmp_path, shim_text: str) -> None:
    out = _run_shim_fn(tmp_path, shim_text, "deploy", "component_begin aws")
    # In deploy mode it might print a progress line, which is fine
    assert "---" not in out


def _macos_shim() -> str:
    return OSShim(OS.MACOS).render()


def _write_secrets(tmp_path, body: str) -> None:
    (tmp_path / "dotgen").mkdir()
    (tmp_path / "dotgen" / "secrets.env").write_text(body)


def _run_template(tmp_path, mode: str, src: str, vars_list: str, *, secrets: str) -> subprocess.CompletedProcess[str]:
    _write_secrets(tmp_path, secrets)
    src_path = tmp_path / "src"
    src_path.write_text(src)
    dst_path = tmp_path / "dst"
    script = tmp_path / "run.sh"
    script.write_text(f"{_macos_shim()}\nexport XDG_CONFIG_HOME={tmp_path}\nexport DOTGEN_MODE={mode}\ninstall_config_template {src_path} {dst_path} '{vars_list}'\n")
    return subprocess.run(["bash", str(script)], capture_output=True, text=True)


def test_install_config_template_renders(tmp_path) -> None:
    res = _run_template(
        tmp_path,
        mode="deploy",
        src="name=${GIT_USER_NAME}\nemail=${GIT_USER_EMAIL}\n",
        vars_list="GIT_USER_NAME GIT_USER_EMAIL",
        secrets='GIT_USER_NAME="Alice"\nGIT_USER_EMAIL="a@example.com"\n',
    )
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "dst").read_text() == "name=Alice\nemail=a@example.com\n"


def test_install_config_template_missing_secrets(tmp_path) -> None:
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


def test_install_config_template_whitelist_preserves_unrelated(tmp_path) -> None:
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


def test_install_config_template_diff_mode_does_not_write(tmp_path) -> None:
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


def test_install_config_template_missing_secrets_file(tmp_path) -> None:
    src_path = tmp_path / "src"
    src_path.write_text("name=${GIT_USER_NAME}\n")
    dst_path = tmp_path / "dst"
    script = tmp_path / "run.sh"
    script.write_text(f"{_macos_shim()}\nexport XDG_CONFIG_HOME={tmp_path}\nexport DOTGEN_MODE=deploy\ninstall_config_template {src_path} {dst_path} 'GIT_USER_NAME'\n")
    res = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert res.returncode != 0
    assert "missing secrets file" in res.stderr
    assert not dst_path.exists()


def test_load_secrets_idempotent(tmp_path) -> None:
    _write_secrets(tmp_path, 'COUNTER="$((${COUNTER:-0}+1))"\n')
    script = tmp_path / "run.sh"
    script.write_text(f'{_macos_shim()}\nexport XDG_CONFIG_HOME={tmp_path}\nexport DOTGEN_MODE=deploy\nload_secrets\nload_secrets\nprintf "%s" "$COUNTER"\n')
    res = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "1"


def test_debian_shim_handles_missing_sudo(tmp_path) -> None:
    shim = OSShim(OS.DEBIAN).render()
    script = tmp_path / "run.sh"

    # Mock pkg_installed to return false, and bin_exists to return false for sudo
    script.write_text(
        textwrap.dedent(f"""\
        {shim}
        DOTGEN_MODE=deploy
        pkg_installed() {{ return 1; }}
        bin_exists() {{ if [ "$1" = "sudo" ]; then return 1; else command -v "$1" >/dev/null; fi; }}
        # Mock apt-get to just echo what it would do
        apt-get() {{ echo "apt-get $*"; }}

        install_package mypkg
    """)
    )

    res = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert res.returncode == 0
    assert "apt-get install -y mypkg" in res.stdout
    assert "sudo" not in res.stdout
