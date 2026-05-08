import re
import subprocess

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
        assert found == canonical, (
            f"{os.value} differs: "
            f"missing={canonical - found} extra={found - canonical}"
        )


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
    "dnf ",
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
        assert not any(t in body for t in _SIDE_EFFECT_TOKENS), (
            f"{fn} has side effects without a diff-mode branch:\n{body}"
        )
