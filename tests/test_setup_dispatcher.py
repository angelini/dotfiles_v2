import subprocess
from pathlib import Path

import pytest

from dotgen.artifact import FakeArtifactBuilder
from dotgen.environment import Environment
from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_env
from dotgen.types import OS, EnvironmentRole, PkgMgr


@pytest.fixture(scope="module")
def built_macos(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("dispatch") / "macos"
    build_env(ENVIRONMENTS["macos"], out, artifact_builder=FakeArtifactBuilder())
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


def test_diff_mode_is_rejected(built_macos: Path) -> None:
    r = _run(built_macos / "setup.sh", "diff")
    assert r.returncode == 2
    assert "unknown mode: diff" in r.stderr
    assert "usage:" in r.stderr


def test_help_prints_deploy_only_usage_and_exits_zero(built_macos: Path) -> None:
    r = _run(built_macos / "setup.sh", "--help")
    assert r.returncode == 0
    assert "usage:" in r.stdout
    assert "deploy" in r.stdout
    assert "diff" not in r.stdout


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


def _run_cachyos_preflight(
    tmp_path: Path,
    os_release: str | None,
    *,
    with_sudo: bool = True,
    with_pacman: bool = True,
    pacman_ok: bool = True,
    sudo_ok: bool = True,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bundle = tmp_path / "cachyos"
    build_env(Environment("cachyos-test", OS.CACHYOS, PkgMgr.PACMAN, EnvironmentRole.WORKSTATION), bundle, artifact_builder=FakeArtifactBuilder())
    os_release_path = tmp_path / "os-release"
    if os_release is not None:
        os_release_path.write_text(os_release)
    shim = bundle / "os_shim.sh"
    shim.write_text(shim.read_text().replace("/etc/os-release", str(os_release_path)))

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "id").write_text("#!/bin/sh\necho 1000\n")
    (fake_bin / "id").chmod(0o755)
    (fake_bin / "dirname").symlink_to("/usr/bin/dirname")
    mutation_log = tmp_path / "mutations"
    if with_sudo:
        (fake_bin / "sudo").write_text(f"#!/bin/sh\nprintf 'sudo %s\\n' \"$*\" >> {mutation_log}.auth\n[ \"$1\" != -v ] || exit {0 if sudo_ok else 1}\n")
        (fake_bin / "sudo").chmod(0o755)
    if with_pacman:
        version_status = 0 if pacman_ok else 99
        (fake_bin / "pacman").write_text(
            f"#!/bin/sh\n[ \"$1\" = --version ] && {{ echo 'Pacman v7'; exit {version_status}; }}\nprintf 'pacman %s\\n' \"$*\" >> {mutation_log}\nexit 99\n"
        )
        (fake_bin / "pacman").chmod(0o755)

    result = _run(bundle / "setup.sh", "deploy", env={"PATH": str(fake_bin), "HOME": str(tmp_path / "home")})
    return result, mutation_log


@pytest.mark.parametrize(
    "os_release",
    [
        'ID=arch\nID_LIKE=arch\n',
        'ID=cachyos\nID_LIKE=linux\n',
        'ID=cachyos\nBROKEN\nID_LIKE=arch\n',
        'ID=cachyos\nID=cachyos\nID_LIKE=arch\n',
        None,
    ],
    ids=["wrong-os", "wrong-family", "malformed", "duplicate-id", "missing-file"],
)
def test_cachyos_identity_preflight_mutates_nothing(tmp_path: Path, os_release: str | None) -> None:
    result, mutation_log = _run_cachyos_preflight(tmp_path, os_release)
    assert result.returncode != 0
    assert "CachyOS preflight" in result.stderr
    assert not mutation_log.exists()


def test_cachyos_missing_sudo_mutates_nothing(tmp_path: Path) -> None:
    result, mutation_log = _run_cachyos_preflight(tmp_path, "ID=cachyos\nID_LIKE=arch\n", with_sudo=False)
    assert result.returncode == 2
    assert "deploy requires sudo" in result.stderr
    assert not mutation_log.exists()


def test_cachyos_preflight_requires_pacman_before_sudo_authentication(tmp_path: Path) -> None:
    result, mutation_log = _run_cachyos_preflight(tmp_path, 'NAME="CachyOS Linux"\nID="cachyos"\nID_LIKE="arch"\n', with_pacman=False)
    assert result.returncode != 0
    assert "pacman is required" in result.stderr
    assert not mutation_log.exists()
    assert not Path(f"{mutation_log}.auth").exists()


def test_cachyos_preflight_rejects_unusable_pacman_before_sudo_authentication(tmp_path: Path) -> None:
    result, mutation_log = _run_cachyos_preflight(tmp_path, "ID=cachyos\nID_LIKE=arch\n", pacman_ok=False)
    assert result.returncode != 0
    assert "present but not runnable" in result.stderr
    assert not mutation_log.exists()
    assert not Path(f"{mutation_log}.auth").exists()


def test_cachyos_failed_sudo_authentication_mutates_nothing(tmp_path: Path) -> None:
    result, mutation_log = _run_cachyos_preflight(tmp_path, "ID=cachyos\nID_LIKE=arch\n", sudo_ok=False)
    assert result.returncode == 2
    assert "unable to authenticate with sudo" in result.stderr
    assert not mutation_log.exists()
    assert Path(f"{mutation_log}.auth").read_text() == "sudo -v\n"


def test_deployment_preflight_order_precedes_auth_and_mutation(built_macos: Path) -> None:
    setup = (built_macos / "setup.sh").read_text()
    assert setup.index('if ! bin_exists sudo; then') < setup.index("deployment_preflight") < setup.index("if ! sudo -v; then")
    assert setup.index("if ! sudo -v; then") < setup.index("bin_exists envsubst || install_package gettext") < setup.index("update_pkg_index")


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
    assert 'ssh -o ClearAllForwardings=yes -t -- "{{target}}"' in justfile
    assert 'tar xzf "{{env}}.tar.gz"' in justfile
    assert 'bash "{{env}}/setup.sh" deploy' in justfile


def test_just_deploy_removes_stale_bundle_and_archive() -> None:
    justfile = (Path(__file__).parents[1] / "justfile").read_text()
    assert 'rm -rf -- "{{env}}"' in justfile
    assert 'rm -f -- "{{env}}.tar.gz"' in justfile


def test_vm_recipes_reject_pi_sandbox() -> None:
    justfile = (Path(__file__).parents[1] / "justfile").read_text()
    assert "_vm-test-preflight:" in justfile
    assert 'test-vm env="debian": _vm-test-preflight' in justfile
    assert "test-vm-all: _vm-test-preflight" in justfile
    assert '"${DOTGEN_PI_SANDBOX:-}" = 1' in justfile
    assert "Rerun from a regular terminal or start Pi with pi-unsafe." in justfile
