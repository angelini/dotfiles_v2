import re
import subprocess
from pathlib import Path

import pytest

from dotgen.artifact import FakeArtifactBuilder
from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_all, build_env
from dotgen.shim import SHIM_FUNCTIONS


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
def test_build_env_emits_four_files(tmp_path: Path, env_name: str) -> None:
    out = tmp_path / env_name
    build_env(ENVIRONMENTS[env_name], out, artifact_builder=FakeArtifactBuilder())

    for fname in ("setup.sh", "alias.sh", ".bashrc", "os_shim.sh"):
        path = out / fname
        assert path.is_file(), f"missing {fname}"
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_build_env_removes_stale_output(tmp_path: Path) -> None:
    out = tmp_path / "macos"
    stale = out / "config" / "pi" / "agent" / "settings.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale\n")

    build_env(ENVIRONMENTS["macos"], out, artifact_builder=FakeArtifactBuilder())

    assert not stale.exists()


def test_bashrc_returns_before_non_interactive_setup(tmp_path: Path) -> None:
    build_env(ENVIRONMENTS["debian"], tmp_path, artifact_builder=FakeArtifactBuilder())

    subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; ! declare -F bin_exists >/dev/null',
            "bash",
            str(tmp_path / ".bashrc"),
        ],
        check=True,
    )


def test_build_all_emits_one_dir_per_env(tmp_path: Path) -> None:
    build_all(tmp_path, artifact_builder=FakeArtifactBuilder())
    for name in ENVIRONMENTS:
        assert (tmp_path / name).is_dir()
        assert (tmp_path / name / "setup.sh").is_file()


def test_shim_contains_all_contract_functions(tmp_path: Path) -> None:
    build_env(ENVIRONMENTS["macos"], tmp_path, artifact_builder=FakeArtifactBuilder())
    text = (tmp_path / "os_shim.sh").read_text()
    for fn in SHIM_FUNCTIONS:
        assert re.search(rf"^{re.escape(fn)}\(\) [{{(]", text, re.MULTILINE), f"missing shim function: {fn}"


def test_build_env_emits_dockerfile_only_for_docker_env(tmp_path: Path) -> None:
    # Docker env should have Dockerfile
    out_docker = tmp_path / "debian-docker"
    build_env(ENVIRONMENTS["debian-docker"], out_docker, artifact_builder=FakeArtifactBuilder())
    assert (out_docker / "Dockerfile").is_file()

    # Non-docker env should NOT have Dockerfile
    out_macos = tmp_path / "macos"
    build_env(ENVIRONMENTS["macos"], out_macos, artifact_builder=FakeArtifactBuilder())
    assert not (out_macos / "Dockerfile").exists()
