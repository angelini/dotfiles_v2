import shutil
import subprocess
from pathlib import Path

import pytest

from dotgen.render import build_all


@pytest.fixture(scope="module")
def built_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("shellcheck")
    build_all(root)
    return root


def test_shellcheck_clean(built_root: Path) -> None:
    if not shutil.which("shellcheck"):
        pytest.skip("shellcheck not installed")
    files = sorted(built_root.glob("*/*.sh")) + sorted(built_root.glob("*/.bashrc"))
    cmd = [
        "shellcheck",
        "-s",
        "bash",
        "--exclude=SC1090,SC1091",
        *(str(f) for f in files),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
