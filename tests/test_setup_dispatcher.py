import subprocess
from pathlib import Path

import pytest

from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_env


@pytest.fixture(scope="module")
def built_macos(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("dispatch") / "macos"
    build_env(ENVIRONMENTS["macos"], out)
    return out


def _run(setup: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(setup), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_no_arg_exits_with_usage(built_macos: Path) -> None:
    r = _run(built_macos / "setup.sh")
    assert r.returncode == 2
    assert "usage:" in r.stderr


def test_unknown_mode_exits_with_usage(built_macos: Path) -> None:
    r = _run(built_macos / "setup.sh", "garbage")
    assert r.returncode == 2
    assert "unknown mode: garbage" in r.stderr


def test_help_prints_usage_and_exits_zero(built_macos: Path) -> None:
    r = _run(built_macos / "setup.sh", "--help")
    assert r.returncode == 0
    assert "usage:" in r.stdout
