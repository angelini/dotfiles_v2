import subprocess
from pathlib import Path

import pytest

from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_all, build_env
from dotgen.shim import SHIM_FUNCTIONS


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
def test_build_env_emits_four_files(tmp_path: Path, env_name: str) -> None:
    out = tmp_path / env_name
    build_env(ENVIRONMENTS[env_name], out)

    for fname in ("setup.sh", "alias.sh", ".bashrc", "os_shim.sh"):
        path = out / fname
        assert path.is_file(), f"missing {fname}"
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_bashrc_returns_before_non_interactive_setup(tmp_path: Path) -> None:
    build_env(ENVIRONMENTS["debian"], tmp_path)

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
    build_all(tmp_path)
    for name in ENVIRONMENTS:
        assert (tmp_path / name).is_dir()
        assert (tmp_path / name / "setup.sh").is_file()


def test_shim_contains_all_contract_functions(tmp_path: Path) -> None:
    build_env(ENVIRONMENTS["macos"], tmp_path)
    text = (tmp_path / "os_shim.sh").read_text()
    for fn in SHIM_FUNCTIONS:
        assert f"{fn}() {{" in text, f"missing shim function: {fn}"


def test_build_env_emits_dockerfile_only_for_docker_env(tmp_path: Path) -> None:
    # Docker env should have Dockerfile
    out_docker = tmp_path / "debian-docker"
    build_env(ENVIRONMENTS["debian-docker"], out_docker)
    assert (out_docker / "Dockerfile").is_file()

    # Non-docker env should NOT have Dockerfile
    out_macos = tmp_path / "macos"
    build_env(ENVIRONMENTS["macos"], out_macos)
    assert not (out_macos / "Dockerfile").exists()
