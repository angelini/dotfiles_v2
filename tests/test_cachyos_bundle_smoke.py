import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dotgen.artifact import FakeArtifactBuilder
from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_env
from dotgen.types import OS, EnvironmentRole, PkgMgr


@dataclass(frozen=True)
class PackageSmoke:
    name: str = "package_smoke"

    def applies_to(self, _env: Environment) -> bool:
        return True

    def render(self, _env: Environment) -> Fragment:
        return Fragment(
            setup="""\
install_packages alpha beta
service_enable dotgen-smoke.service
install_config "$DIR/config/smoke/value" "$HOME/.config/smoke/value"
""",
            configs=(ConfigFile("smoke/value", "managed\n"),),
        )


@dataclass(frozen=True)
class UserServiceSmoke:
    name: str = "user_service_smoke"

    def applies_to(self, _env: Environment) -> bool:
        return True

    def render(self, _env: Environment) -> Fragment:
        return Fragment(
            setup="""\
systemctl --user enable --now dotgen-user-smoke.service
ssh -G smoke-host >/dev/null
"""
        )


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _run(bundle: Path, home: Path, fake_bin: Path, state: Path, log: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(bundle / "setup.sh"), "deploy"],
        capture_output=True,
        text=True,
        check=False,
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "SMOKE_LOG": str(log),
            "SMOKE_STATE": str(state),
        },
    )


def test_generated_cachyos_bundle_orders_components_and_converges_with_fake_host(tmp_path: Path) -> None:
    production = tmp_path / "production"
    build_env(ENVIRONMENTS["cachyos"], production, artifact_builder=FakeArtifactBuilder())
    setup = (production / "setup.sh").read_text()
    expected_names = [
        component.name
        for component in ENVIRONMENTS["cachyos"].components
        if component.applies_to(ENVIRONMENTS["cachyos"]) and component.render(ENVIRONMENTS["cachyos"]).setup
    ]
    headers = [line.removeprefix("# --- ").removesuffix(" ---") for line in setup.splitlines() if line.startswith("# --- ")]

    assert headers == expected_names
    assert setup.index("deployment_preflight") < setup.index("sudo -v") < setup.index("update_pkg_index")
    assert headers.index("node_fnm") < headers.index("steps") < headers.index("pi_agent")
    assert headers.index("zed") < headers.index("docker") < headers.index("zed_host_bridge")
    assert headers[-2:] == ["git_setup", "dotfiles_deploy"]

    smoke_env = Environment(
        "cachyos-smoke",
        OS.CACHYOS,
        PkgMgr.PACMAN,
        EnvironmentRole.WORKSTATION,
        components=(PackageSmoke(), UserServiceSmoke()),
    )
    bundle = tmp_path / "smoke"
    build_env(smoke_env, bundle, artifact_builder=FakeArtifactBuilder())
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="CachyOS Linux"\nID=cachyos\nID_LIKE=arch\n')
    shim = bundle / "os_shim.sh"
    shim.write_text(shim.read_text().replace("/etc/os-release", str(os_release)))

    home = tmp_path / "home"
    secrets = home / ".config/dotgen/secrets.env"
    secrets.parent.mkdir(parents=True)
    secrets.write_text("# smoke test has no secrets\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "installed"
    log = tmp_path / "commands.log"

    _write_executable(fake_bin / "id", "#!/bin/sh\n[ \"${1-}\" = -u ] && { echo 1000; exit 0; }\nexec /usr/bin/id \"$@\"\n")
    _write_executable(
        fake_bin / "sudo",
        """#!/bin/sh
printf 'sudo %s\n' "$*" >> "$SMOKE_LOG"
[ "${1-}" = -v ] && exit 0
exec "$@"
""",
    )
    _write_executable(
        fake_bin / "pacman",
        """#!/bin/sh
printf 'pacman %s\n' "$*" >> "$SMOKE_LOG"
[ "${1-}" = --version ] && { echo 'Pacman v7'; exit 0; }
if [ "${1-}" = -Qq ]; then
  grep -Fxq "$3" "$SMOKE_STATE" 2>/dev/null
  exit $?
fi
if [ "${1-}" = -S ]; then
  shift 4
  for pkg in "$@"; do
    grep -Fxq "$pkg" "$SMOKE_STATE" 2>/dev/null || printf '%s\n' "$pkg" >> "$SMOKE_STATE"
  done
  exit 0
fi
[ "${1-}" = -Syu ] && exit 0
exit 99
""",
    )
    _write_executable(
        fake_bin / "systemctl",
        """#!/bin/sh
printf 'systemctl %s\n' "$*" >> "$SMOKE_LOG"
exit 0
""",
    )
    _write_executable(
        fake_bin / "ssh",
        """#!/bin/sh
printf 'ssh %s\n' "$*" >> "$SMOKE_LOG"
[ "${1-}" = -G ] && printf 'host %s\n' "${2-}"
exit 0
""",
    )
    _write_executable(fake_bin / "envsubst", "#!/bin/sh\nexec /bin/cat\n")

    first = _run(bundle, home, fake_bin, state, log)
    assert first.returncode == 0, first.stderr
    assert first.stdout.index("package_smoke...") < first.stdout.index("user_service_smoke...")
    managed = home / ".config/smoke/value"
    first_digest = hashlib.sha256(managed.read_bytes()).hexdigest()

    second = _run(bundle, home, fake_bin, state, log)
    assert second.returncode == 0, second.stderr
    assert hashlib.sha256(managed.read_bytes()).hexdigest() == first_digest
    assert state.read_text().splitlines() == ["alpha", "beta"]

    commands = log.read_text().splitlines()
    assert sum(line == "pacman -S --needed --noconfirm -- alpha beta" for line in commands) == 1
    assert sum(line == "pacman -Syu --noconfirm" for line in commands) == 2
    assert sum(line == "systemctl enable --now dotgen-smoke.service" for line in commands) == 2
    assert sum(line == "systemctl --user enable --now dotgen-user-smoke.service" for line in commands) == 2
    assert sum(line == "ssh -G smoke-host" for line in commands) == 2
    assert sum(line == "sudo -v" for line in commands) == 2
    assert os.stat(managed).st_mode & 0o777 == 0o644
