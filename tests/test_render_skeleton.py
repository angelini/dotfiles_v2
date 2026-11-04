import os
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from dotgen.artifact import FakeArtifactBuilder
from dotgen.components.dotfiles_deploy import DotfilesDeploy
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
    secrets = tmp_path / ".config/dotgen/secrets.env"
    secrets.parent.mkdir(parents=True)
    secrets.write_text("DOTGEN_TEST_SECRET=should-not-load\n")

    subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; ! declare -F bin_exists >/dev/null && [ -z "${DOTGEN_TEST_SECRET+x}" ]',
            "bash",
            str(tmp_path / ".bashrc"),
        ],
        env={"HOME": str(tmp_path), "PATH": os.defpath},
        check=True,
    )


@pytest.fixture
def bash_home(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    env = replace(ENVIRONMENTS["debian"], components=(DotfilesDeploy(),))
    build_env(env, bundle, artifact_builder=FakeArtifactBuilder())
    (bundle / ".bashrc").rename(tmp_path / ".bashrc")
    (bundle / "config/bash/bash_profile").rename(tmp_path / ".bash_profile")
    return tmp_path


@pytest.mark.parametrize("login", [False, True])
@pytest.mark.parametrize("xdg", [False, True])
@pytest.mark.parametrize("allexport", [False, True])
def test_bash_sessions_export_secrets(bash_home: Path, login: bool, xdg: bool, allexport: bool) -> None:
    config = bash_home / ("custom-config" if xdg else ".config")
    secrets = config / "dotgen/secrets.env"
    secrets.parent.mkdir(parents=True)
    secrets.write_text("""EBAY_APP_ID='test app'
EBAY_CLIENT_SECRET='literal $value'
EXA_API_KEY=exa-test
CONTEXT7_API_KEY=context7-test
GEMINI_API_KEY=gemini-test
""")
    env = {"HOME": str(bash_home), "PATH": os.defpath, "TERM": "dumb"}
    if xdg:
        env["XDG_CONFIG_HOME"] = str(config)
        default = bash_home / ".config/dotgen/secrets.env"
        default.parent.mkdir(parents=True)
        default.write_text("EBAY_APP_ID=wrong-file\n")
    startup = ["--login"] if login else ["--noprofile", "--rcfile", str(bash_home / ".bashrc")]
    result = subprocess.run(
        [
            "bash",
            *startup,
            "-aic" if allexport else "-ic",
            """DOTGEN_AFTER_LOAD=exported
bash --noprofile --norc -c '
printf "%s\\n" "$EBAY_APP_ID" "$EBAY_CLIENT_SECRET" "$EXA_API_KEY" "$CONTEXT7_API_KEY" "$GEMINI_API_KEY" "${DOTGEN_AFTER_LOAD-unexported}"
'
""",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "test app",
        "literal $value",
        "exa-test",
        "context7-test",
        "gemini-test",
        "exported" if allexport else "unexported",
    ]


def test_bash_session_without_secrets_starts_quietly(bash_home: Path) -> None:
    result = subprocess.run(
        ["bash", "--noprofile", "--rcfile", str(bash_home / ".bashrc"), "-ic", "printf ready"],
        env={"HOME": str(bash_home), "PATH": os.defpath, "TERM": "dumb"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ready"
    assert "secrets.env" not in result.stderr


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
