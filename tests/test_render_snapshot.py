import os
from pathlib import Path

import pytest

from dotgen.environment import ENVIRONMENTS
from dotgen.render import build_env

GOLDEN_ROOT = Path(__file__).parent / "golden"
SNAPSHOT_FILES = ("setup.sh", "alias.sh", ".bashrc", "os_shim.sh")
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


@pytest.fixture(scope="module")
def built_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("snapshot")
    for name, env in ENVIRONMENTS.items():
        build_env(env, root / name)
    return root


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
@pytest.mark.parametrize("fname", SNAPSHOT_FILES)
def test_snapshot_matches_golden(built_root: Path, env_name: str, fname: str) -> None:
    actual = (built_root / env_name / fname).read_text()
    golden = GOLDEN_ROOT / env_name / fname

    if UPDATE or not golden.exists():
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual)
        if not UPDATE:
            pytest.skip(f"created missing golden {golden.relative_to(GOLDEN_ROOT.parent)}")
        return

    assert actual == golden.read_text(), (
        f"snapshot drift for {env_name}/{fname}; "
        f"re-run with UPDATE_GOLDEN=1 if intended"
    )
