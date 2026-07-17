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


def _run(setup: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(setup), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
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


def test_deploy_rejects_root(tmp_path: Path, built_macos: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "id").write_text("#!/bin/sh\necho 0\n")
    (fake_bin / "id").chmod(0o755)
    (fake_bin / "dirname").symlink_to("/usr/bin/dirname")

    r = _run(built_macos / "setup.sh", "deploy", env={"PATH": str(fake_bin)})
    assert r.returncode == 2
    assert "regular user, not root" in r.stderr


def test_deploy_requires_sudo(tmp_path: Path, built_macos: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "id").write_text("#!/bin/sh\necho 1000\n")
    (fake_bin / "id").chmod(0o755)
    (fake_bin / "dirname").symlink_to("/usr/bin/dirname")

    r = _run(built_macos / "setup.sh", "deploy", env={"PATH": str(fake_bin)})
    assert r.returncode == 2
    assert "deploy requires sudo" in r.stderr


def test_just_install_passes_deploy() -> None:
    justfile = Path(__file__).parents[1] / "justfile"
    assert "bash dist/{{env}}/setup.sh deploy" in justfile.read_text()


def test_just_package_excludes_macos_extended_attributes() -> None:
    justfile = Path(__file__).parents[1] / "justfile"
    assert "COPYFILE_DISABLE=1 tar --no-xattrs" in justfile.read_text()


def test_just_deploy_builds_transfers_and_runs_with_tty() -> None:
    justfile = (Path(__file__).parents[1] / "justfile").read_text()
    assert "deploy env target:" in justfile
    assert 'just build "{{env}}"' in justfile
    assert 'scp -- "dist/{{env}}.tar.gz" "{{target}}:"' in justfile
    assert 'ssh -t -- "{{target}}"' in justfile
    assert 'tar xzf "{{env}}.tar.gz"' in justfile
    assert 'bash "{{env}}/setup.sh" deploy' in justfile


def test_just_deploy_removes_stale_bundle_and_archive() -> None:
    justfile = (Path(__file__).parents[1] / "justfile").read_text()
    assert 'rm -rf -- "{{env}}"' in justfile
    assert 'rm -f -- "{{env}}.tar.gz"' in justfile
