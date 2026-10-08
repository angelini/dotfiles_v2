from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from dotgen.components.docker import Docker
from dotgen.registry import ENVIRONMENTS

_VALID_SUBIDS = "alice:100000:65536\n"


@dataclass
class DockerHarness:
    root: Path

    def _socket(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["python3", "-c", "import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.close()", str(path)],
            check=True,
        )

    def events(self) -> list[str]:
        log = self.root / "state" / "events"
        return log.read_text().splitlines() if log.exists() else []

    def run(
        self,
        *,
        env_name: str = "debian",
        os_release: str | None = None,
        arch: str | None = None,
        subuid: str = _VALID_SUBIDS,
        subgid: str = _VALID_SUBIDS,
        marker_state: str = "none",
        package_failure: str | None = None,
        iptables_backend: str = "nf_tables",
        module_failure: bool = False,
        root_socket: str = "absent",
        runtime_path: str = "canonical",
        runtime_mode: str = "700",
        runtime_owner: str = "1000",
        ready_after: int = 0,
        incoming_env: dict[str, str] | None = None,
        systemd: bool = True,
        logind: bool = True,
        cgroup: bool = True,
        account: str = "valid",
        rootful_active: str = "",
        rootless_socket: str = "auto",
        missing_tool: str = "",
        verification_failure: str = "",
        storage_driver: str = "overlayfs",
        reset: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        root, state, fake, home = self.root, self.root / "state", self.root / "bin", self.root / "home"
        if reset:
            shutil.rmtree(root, ignore_errors=True)
        for directory in (state, fake, home):
            directory.mkdir(parents=True, exist_ok=True)
        if systemd:
            (root / "run/systemd/system").mkdir(parents=True, exist_ok=True)
        if cgroup:
            (root / "sys/fs/cgroup").mkdir(parents=True, exist_ok=True)
        (root / "etc").mkdir(exist_ok=True)
        if os_release is None:
            os_release = "ID=cachyos\nID_LIKE=arch\n" if env_name == "cachyos" else "ID=debian\nVERSION_ID=13\nVERSION_CODENAME=trixie\n"
        if arch is None:
            arch = "x86_64" if env_name == "cachyos" else "amd64"
        (root / "etc/os-release").write_text(os_release)
        (root / "etc/subuid").write_text(subuid)
        (root / "etc/subgid").write_text(subgid)
        if cgroup:
            (root / "sys/fs/cgroup/cgroup.controllers").write_text("cpu\n")
        runtime = root / "run/user/1000"
        runtime.mkdir(parents=True, exist_ok=True)
        if ready_after == 0 and not (runtime / "bus").exists():
            self._socket(runtime / "bus")
        if marker_state in {"both", "unit", "unsafe"}:
            marker = home / (".config/systemd/user/docker.service.d/10-dotgen-socket-mode.conf" if env_name == "cachyos" else ".config/systemd/user/docker.service")
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("unsafe\n" if marker_state == "unsafe" else "[Service]\nExecStartPost=/usr/bin/chmod 0600 %t/docker.sock\n")
            if env_name == "cachyos":
                (state / "user-docker.enabled").write_text("enabled\n")
        if marker_state in {"both", "context", "unsafe"}:
            marker = home / ".docker/contexts/meta/12b961af5feb3e9d39f93b2cefb9a1a944f18d02cca0cac2f04f5a982240605f/meta.json"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
        if root_socket == "stale":
            (root / "var/run").mkdir(parents=True, exist_ok=True)
            (root / "var/run/docker.sock").write_text("stale")
        if root_socket == "live":
            self._socket(root / "var/run/docker.sock")
        if rootless_socket == "stale":
            (runtime / "docker.sock").write_text("stale")
        elif rootless_socket in {"live", "foreign"}:
            self._socket(runtime / "docker.sock")

        fragment = Docker().render(ENVIRONMENTS[env_name])
        setup = fragment.setup
        bundle = root / "bundle"
        for config in fragment.configs:
            target = bundle / "config" / config.dest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(config.content)
        for production, isolated in {
            "/etc/os-release": root / "etc/os-release",
            "/etc/subuid": root / "etc/subuid",
            "/etc/subgid": root / "etc/subgid",
            "/run/systemd/system": root / "run/systemd/system",
            "/sys/fs/cgroup/cgroup.controllers": root / "sys/fs/cgroup/cgroup.controllers",
            "/var/run/docker.sock": root / "var/run/docker.sock",
            "/run/user/": root / "run/user/",
        }.items():
            setup = setup.replace(production, str(isolated) + ("/" if production.endswith("/") else ""))
        (root / "setup.sh").write_text(setup)
        dispatcher = textwrap.dedent(
            """#!/usr/bin/env bash
            set -u
            name="$(basename "$0")"
            log() { printf '%s\n' "$*" >> "$STATE/events"; }
            socket() {
  [ -S "$1" ] && return 0
  mkdir -p "$(dirname "$1")"
  python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.close()' "$1"
}
            case "$name" in
            ps) [ "$SYSTEMD" = 1 ] && echo systemd || echo init ;;
            dpkg) echo "$ARCH" ;;
            uname) [ "${1:-}" = -r ] && echo test-kernel || echo "$ARCH" ;;
            id)
  case "${1:-}" in
  -un) [ "$ACCOUNT" = name ] && echo Alice || echo alice ;;
  -u|-g) [ "$ACCOUNT" = zero ] && echo 0 || echo 1000 ;;
  *) echo 1000 ;;
  esac ;;
            getent) [ "$ACCOUNT" = missing ] && exit 2; [ "$ACCOUNT" = mismatch ] && echo "alice:x:999:1000::${HOME}:/bin/bash" || echo "alice:x:1000:1000::${HOME}:/bin/bash" ;;
            stat)
  if [[ "${*: -1}" = *docker.sock ]]; then
    [ "$2" = "%u" ] && { [ "$ROOTLESS_SOCKET" = foreign ] && echo 1001 || echo 1000; } || echo 600
  elif [[ "${*: -1}" = *10-dotgen-socket-mode.conf ]]; then
    [ "$2" = "%u" ] && echo 1000 || echo 600
  else
    [ "$2" = "%u" ] && echo "$RUNTIME_OWNER" || echo "$RUNTIME_MODE"
  fi ;;
            ss) [ "$ROOT_SOCKET" = live ] && echo "u_str LISTEN 0 0 $ROOT/var/run/docker.sock" ;;
            sleep) log WAIT; n=$(cat "$STATE/waits" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$STATE/waits"; if [ "$n" = "$READY_AFTER" ]; then socket "$ROOT/run/user/1000/bus"; fi ;;
            grep) case "$*" in */proc/modules*|*/modules.builtin*) exit 1 ;; *) /usr/bin/grep "$@" ;; esac ;;
            loginctl)
  log "LOGINCTL $*"
  case "${1:-}" in
  show-user) [ "$RUNTIME_PATH" = canonical ] && echo "$ROOT/run/user/1000" || echo "$RUNTIME_PATH" ;;
  user-status) echo loginctl-diagnostic >&2 ;;
  esac ;;
            systemctl)
              log "SYSTEMCTL $*"
              if [ "${1:-}" = --user ]; then
                shift
                case "${1:-}" in
                show-environment) [ -S "$ROOT/run/user/1000/bus" ] ;;
                is-enabled) cat "$STATE/user-docker.enabled" 2>/dev/null || echo disabled ;;
                enable)
                  log "ENABLE_USER $*"
                  [ "$VERIFICATION_FAILURE" != service ] || exit 1
                  socket "$ROOT/run/user/1000/docker.sock"
                  chmod 0600 "$ROOT/run/user/1000/docker.sock"
                  echo enabled > "$STATE/user-docker.enabled"
                  echo active > "$STATE/user-docker.active"
                  ;;
                is-active) [ "$(cat "$STATE/user-docker.active" 2>/dev/null || echo inactive)" = active ] ;;
                daemon-reload) log DAEMON_RELOAD ;;
                esac
              elif [ "${1:-}" = is-enabled ]; then unit="${@: -1}"; cat "$STATE/$unit.enabled" 2>/dev/null || echo disabled
              elif [ "${1:-}" = is-active ]; then
                case "${*: -1}" in
                systemd-logind.service) [ "$LOGIND" = 1 ] ;;
                user@*) [ "$(cat "$STATE/user.active" 2>/dev/null || echo inactive)" = active ] ;;
                *) [ "${*: -1}" = "$ROOTFUL_ACTIVE" ] || [ "$(cat "$STATE/${*: -1}.active" 2>/dev/null || echo inactive)" = active ] ;;
                esac
              elif [ "${1:-}" = show ]; then echo "$SYSTEM_STATE"
              elif [ "${1:-}" = start ]; then echo active > "$STATE/user.active"
              elif [ "${1:-}" = status ]; then echo user-unit-diagnostic >&2
              fi ;;
            iptables) echo "iptables v1.8.11 ($IPTABLES_BACKEND)" ;;
            modprobe) log "MODPROBE $*"; [ "$MODULE_FAILURE" = 0 ] ;;
            dockerd-rootless-setuptool.sh)
  log "SETUP DOCKER_HOST=${DOCKER_HOST-unset} DOCKER_CONTEXT=${DOCKER_CONTEXT-unset} XDG_CONFIG_HOME=${XDG_CONFIG_HOME-unset} DOCKER_CONFIG=${DOCKER_CONFIG-unset}"
  mkdir -p "$HOME/.config/systemd/user" "$HOME/.docker/contexts/meta/12b961af5feb3e9d39f93b2cefb9a1a944f18d02cca0cac2f04f5a982240605f"
  : > "$HOME/.config/systemd/user/docker.service"
  : > "$HOME/.docker/contexts/meta/12b961af5feb3e9d39f93b2cefb9a1a944f18d02cca0cac2f04f5a982240605f/meta.json" ;;
            docker)
  log "DOCKER $* DOCKER_HOST=${DOCKER_HOST-unset} DOCKER_CONTEXT=${DOCKER_CONTEXT-unset} XDG_CONFIG_HOME=${XDG_CONFIG_HOME-unset} DOCKER_CONFIG=${DOCKER_CONFIG-unset}"
  case "$*" in
  *"context create rootless"*)
    marker="$HOME/.docker/contexts/meta/12b961af5feb3e9d39f93b2cefb9a1a944f18d02cca0cac2f04f5a982240605f/meta.json"
    mkdir -p "${marker%/*}"
    : > "$marker"
    ;;
  *"context inspect rootless"*) [ "$VERIFICATION_FAILURE" = endpoint ] && echo unix:///wrong/docker.sock || echo "unix://$ROOT/run/user/1000/docker.sock" ;;
  *"context show"*) echo rootless ;;
  *"SecurityOptions"*) [ "$VERIFICATION_FAILURE" = security ] && echo '[]' || echo '["rootless"]' ;;
  *"CgroupVersion"*) [ "$VERIFICATION_FAILURE" = cgroup ] && echo 1 || echo 2 ;;
  *"{{.Driver}}"*) [ "$VERIFICATION_FAILURE" = driver ] && echo vfs || echo "$STORAGE_DRIVER" ;;
  *"compose version"*) [ "$VERIFICATION_FAILURE" != compose ] ;;
  *"buildx version"*) [ "$VERIFICATION_FAILURE" != buildx ] ;;
  esac ;;
            esac
            """
        )
        command = fake / "command"
        command.write_text(dispatcher)
        command.chmod(0o755)
        for name in (
            "ps",
            "dpkg",
            "uname",
            "grep",
            "id",
            "getent",
            "stat",
            "ss",
            "sleep",
            "loginctl",
            "systemctl",
            "iptables",
            "modprobe",
            "docker",
            "dockerd-rootless-setuptool.sh",
            "newuidmap",
            "newgidmap",
            "getsubids",
            "dockerd",
            "rootlesskit",
            "slirp4netns",
            "fuse-overlayfs",
        ):
            if name == missing_tool:
                continue
            link = fake / name
            if not link.exists():
                link.symlink_to(command.name)
        prelude = textwrap.dedent(
            """set -u
            error() { printf '%s\n' "$*" >&2; }
            bin_exists() { [ "$1" != "$MISSING_TOOL" ] && command -v "$1" >/dev/null; }
            sudo() { echo "SUDO $*" >> "$STATE/events"; while [[ "${1:-}" = *=* ]]; do shift; done; "$@"; }
            install_package() { echo "INSTALL $1" >> "$STATE/events"; }
            install_packages() { echo "INSTALLS $*" >> "$STATE/events"; [ -z "$PACKAGE_FAILURE" ] || return 1; }
            download_script_sha256() {
              echo "DOWNLOAD_SCRIPT $*" >> "$STATE/events"
              [ "$1" != "$MISSING_TOOL" ] || return 0
              mkdir -p "$HOME/bin"
              printf '#!/usr/bin/env bash\n' > "$HOME/bin/$1"
              chmod 0755 "$HOME/bin/$1"
            }
            add_repo() { echo "ADD_REPO" >> "$STATE/events"; }
            remove_packages() { echo "REMOVE $*" >> "$STATE/events"; }
            update_pkg_index() { echo "UPDATE_INDEX" >> "$STATE/events"; }
            service_mask() {
              for unit in "$@"; do
                echo masked > "$STATE/$unit.enabled"
                echo inactive > "$STATE/$unit.active"
              done
              echo "MASK $*" >> "$STATE/events"
            }
            """
        )
        script = root / "run.sh"
        script.write_text(prelude + "\nsource " + str(root / "setup.sh") + "\n")
        inherited_env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"XDG_RUNTIME_DIR", "DOCKER_HOST", "DOCKER_CONTEXT", "XDG_CONFIG_HOME", "DOCKER_CONFIG"}
        }
        env = inherited_env | {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "STATE": str(state),
            "ROOT": str(root),
            "DIR": str(bundle),
            "HOME": str(home),
            "ARCH": arch,
            "ROOT_SOCKET": root_socket,
            "RUNTIME_PATH": str(runtime) if runtime_path == "canonical" else runtime_path,
            "RUNTIME_MODE": runtime_mode,
            "RUNTIME_OWNER": runtime_owner,
            "READY_AFTER": str(ready_after),
            "PACKAGE_FAILURE": package_failure or "",
            "IPTABLES_BACKEND": iptables_backend,
            "MODULE_FAILURE": "1" if module_failure else "0",
            "SYSTEMD": "1" if systemd else "0",
            "LOGIND": "1" if logind else "0",
            "SYSTEM_STATE": "running",
            "ACCOUNT": account,
            "ROOTFUL_ACTIVE": rootful_active,
            "ROOTLESS_SOCKET": rootless_socket,
            "VERIFICATION_FAILURE": verification_failure,
            "STORAGE_DRIVER": storage_driver,
            "MISSING_TOOL": missing_tool,
        }
        if incoming_env:
            env.update(incoming_env)
        return subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)


@pytest.fixture
def docker_harness() -> Iterator[DockerHarness]:
    with tempfile.TemporaryDirectory(prefix="dotgen-docker-", dir="/tmp") as temp_dir:
        yield DockerHarness(Path(temp_dir) / "root")


def _barrier(events: list[str]) -> None:
    assert not any(event.startswith(("MASK", "REMOVE", "DOWNLOAD_SCRIPT", "ADD_REPO", "UPDATE_INDEX", "INSTALLS")) for event in events)
    assert "SUDO loginctl enable-linger alice" not in events


@pytest.mark.parametrize("env_name", ["debian", "cachyos"])
def test_docker_setup_is_bash_syntax_clean(tmp_path: Path, env_name: str) -> None:
    script = tmp_path / f"docker-{env_name}.sh"
    script.write_text(Docker().render(ENVIRONMENTS[env_name]).setup)
    assert subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True).returncode == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"arch": "i386"},
        {"os_release": "ID=ubuntu\nVERSION_ID=13\nVERSION_CODENAME=trixie\n"},
        {"systemd": False},
        {"logind": False},
        {"cgroup": False},
        {"account": "name"},
        {"account": "zero"},
        {"account": "missing"},
        {"account": "mismatch"},
        {"marker_state": "unit"},
        {"marker_state": "context"},
        {"subuid": "bad\n"},
        {"subuid": ""},
        {"subuid": "alice:100000:65536\nalice:200000:65536\n"},
        {"subuid": "alice:1:65536\n"},
    ],
)
def test_preflight_barriers_execute_before_package_transition(docker_harness: DockerHarness, kwargs: dict[str, Any]) -> None:
    result = docker_harness.run(**kwargs)
    assert result.returncode != 0
    events = docker_harness.events()
    _barrier(events)
    assert not any(event.startswith("SETUP") for event in events)
    if kwargs.get("marker_state") in {"unit", "context"}:
        assert not any(event.startswith(("SUDO", "LOGINCTL", "ENABLE_USER")) for event in events)


@pytest.mark.parametrize(
    "subids, diagnosis", [("1000:100000:65536\n", ""), ("alice:100000:1\n", "shorter"), ("alice:4294967295:2\n", "overflowing"), ("alice:100000:65536\nbob:100100:65536\n", "overlaps")]
)
def test_subordinate_id_fixture_records_are_executable(docker_harness: DockerHarness, subids: str, diagnosis: str) -> None:
    result = docker_harness.run(subuid=subids, subgid=subids)
    if diagnosis:
        assert result.returncode != 0
        assert diagnosis in result.stderr
        assert "uid " + str(docker_harness.root / "etc/subuid") in result.stderr
        _barrier(docker_harness.events())
    else:
        assert result.returncode == 0, result.stderr


def test_package_safety_root_socket_and_idempotency(docker_harness: DockerHarness) -> None:
    result = docker_harness.run(package_failure="docker-ce")
    assert result.returncode != 0
    events = docker_harness.events()
    mask_index = next(i for i, event in enumerate(events) if event.startswith("MASK"))
    repo_index = next(i for i, event in enumerate(events) if event == "ADD_REPO")
    remove_index = next(i for i, event in enumerate(events) if event.startswith("REMOVE "))
    update_index = next(i for i, event in enumerate(events) if event == "UPDATE_INDEX")
    assert mask_index < repo_index < remove_index < update_index
    assert sum(event.startswith("MASK") for event in events) == 1
    for unit in ("docker.service", "docker.socket"):
        assert (docker_harness.root / f"state/{unit}.enabled").read_text().strip() == "masked"
        assert (docker_harness.root / f"state/{unit}.active").read_text().strip() == "inactive"
    for socket in ("stale", "live"):
        result = docker_harness.run(root_socket=socket)
        assert result.returncode != 0
        assert (docker_harness.root / "var/run/docker.sock").exists()
        assert "unlink" not in "\n".join(docker_harness.events())

    first = docker_harness.run()
    assert first.returncode == 0, first.stderr
    assert sum(event.startswith("SETUP") for event in docker_harness.events()) == 1
    second = docker_harness.run(reset=False)
    assert second.returncode == 0, second.stderr
    assert sum(event.startswith("SETUP") for event in docker_harness.events()) == 1

    result = docker_harness.run(marker_state="both")
    assert result.returncode == 0, result.stderr
    assert not any(event.startswith("SETUP") for event in docker_harness.events())


@pytest.mark.parametrize(("backend", "module"), [("nf_tables", "nf_tables"), ("legacy", "ip_tables")])
def test_iptables_module_is_loaded_before_rootless_setup(docker_harness: DockerHarness, backend: str, module: str) -> None:
    result = docker_harness.run(iptables_backend=backend)
    assert result.returncode == 0, result.stderr
    events = docker_harness.events()
    install_index = next(i for i, event in enumerate(events) if event.startswith("INSTALLS docker-ce"))
    module_index = events.index(f"MODPROBE {module}")
    setup_index = next(i for i, event in enumerate(events) if event.startswith("SETUP"))
    assert install_index < module_index < setup_index


def test_iptables_module_failure_stops_before_rootless_setup(docker_harness: DockerHarness) -> None:
    result = docker_harness.run(module_failure=True)
    assert result.returncode != 0
    assert "failed to load the nf_tables kernel module" in result.stderr
    assert not any(event.startswith("SETUP") for event in docker_harness.events())


def test_runtime_readiness_and_environment_resistance(docker_harness: DockerHarness) -> None:
    result = docker_harness.run(
        ready_after=3, incoming_env={"XDG_RUNTIME_DIR": str(docker_harness.root / "run/user/1000"), "DOCKER_HOST": "bad", "DOCKER_CONTEXT": "bad", "XDG_CONFIG_HOME": "/bad", "DOCKER_CONFIG": "/bad"}
    )
    assert result.returncode == 0, result.stderr
    assert docker_harness.events().count("WAIT") >= 3
    calls = "\n".join(event for event in docker_harness.events() if event.startswith(("SETUP", "DOCKER")))
    assert "DOCKER_HOST=unset" in calls and "DOCKER_CONTEXT=unset" in calls
    assert f"XDG_CONFIG_HOME={docker_harness.root}/home/.config" in calls
    assert f"DOCKER_CONFIG={docker_harness.root}/home/.docker" in calls
    result = docker_harness.run(incoming_env={"XDG_RUNTIME_DIR": "/wrong"})
    assert result.returncode != 0
    assert docker_harness.run(runtime_owner="1001").returncode != 0
    assert docker_harness.run(runtime_mode="755").returncode != 0


def test_user_manager_timeout_is_diagnostic(docker_harness: DockerHarness) -> None:
    result = docker_harness.run(ready_after=31)
    assert result.returncode != 0
    assert "loginctl-diagnostic" in result.stderr
    assert "user-unit-diagnostic" in result.stderr


@pytest.mark.parametrize(
    "kwargs",
    [
        {"arch": "aarch64"},
        {"os_release": "ID=arch\nID_LIKE=arch\n"},
        {"systemd": False},
        {"logind": False},
        {"cgroup": False},
        {"account": "name"},
        {"account": "zero"},
        {"account": "missing"},
        {"account": "mismatch"},
        {"runtime_path": "/wrong"},
        {"runtime_owner": "1001"},
        {"runtime_mode": "755"},
        {"ready_after": 31},
        {"marker_state": "unit"},
        {"marker_state": "context"},
        {"marker_state": "unsafe"},
        {"subuid": "bad\n"},
        {"subuid": ""},
        {"subuid": "alice:100000:65536\nalice:200000:65536\n"},
        {"subuid": "alice:1:65536\n"},
        {"subuid": "alice:4294967295:2\n"},
        {"subuid": "alice:100000:65536\nbob:100100:65536\n"},
        {"rootful_active": "docker.service"},
        {"rootful_active": "docker.socket"},
        {"root_socket": "stale"},
        {"root_socket": "live"},
        {"rootless_socket": "stale"},
        {"rootless_socket": "live"},
        {"marker_state": "both", "rootless_socket": "foreign"},
    ],
)
def test_cachyos_preflight_is_mutation_free(docker_harness: DockerHarness, kwargs: dict[str, Any]) -> None:
    result = docker_harness.run(env_name="cachyos", **kwargs)
    assert result.returncode != 0
    _barrier(docker_harness.events())
    assert not any(event.startswith(("DAEMON_RELOAD", "ENABLE_USER", "DOCKER")) for event in docker_harness.events())


def test_cachyos_package_and_manual_rootless_sequence_is_exact(docker_harness: DockerHarness) -> None:
    result = docker_harness.run(env_name="cachyos")
    assert result.returncode == 0, result.stderr
    events = docker_harness.events()
    first_mask = events.index("MASK docker.service docker.socket")
    standard = events.index("INSTALLS docker docker-compose docker-buildx rootlesskit slirp4netns fuse-overlayfs shadow iptables")
    remove = events.index("REMOVE docker-rootless-extras")
    download = next(i for i, event in enumerate(events) if event.startswith("DOWNLOAD_SCRIPT dockerd-rootless.sh "))
    second_mask = events.index("MASK docker.service docker.socket", first_mask + 1)
    context = next(i for i, event in enumerate(events) if "context create rootless" in event)
    enable = next(i for i, event in enumerate(events) if event.startswith("ENABLE_USER"))
    assert first_mask < standard < remove < download < second_mask < context < enable
    assert "ADD_REPO" not in events and "UPDATE_INDEX" not in events
    setup = Docker().render(ENVIRONMENTS["cachyos"]).setup
    assert "dockerd-rootless-setuptool.sh" not in setup
    assert "--force" not in setup
    assert "usermod" not in setup and "groupadd" not in setup
    assert "/var/lib/docker" not in setup and "/var/lib/containerd" not in setup
    assert "tcp://" not in setup


def test_cachyos_install_rerun_and_existing_state_converge(docker_harness: DockerHarness) -> None:
    first = docker_harness.run(env_name="cachyos")
    assert first.returncode == 0, first.stderr
    assert sum("context create rootless" in event for event in docker_harness.events()) == 1
    second = docker_harness.run(env_name="cachyos", reset=False)
    assert second.returncode == 0, second.stderr
    assert sum("context create rootless" in event for event in docker_harness.events()) == 1

    existing = docker_harness.run(env_name="cachyos", marker_state="both", rootless_socket="live")
    assert existing.returncode == 0, existing.stderr
    assert not any("context create rootless" in event for event in docker_harness.events())


def test_cachyos_module_failure_stops_before_user_setup(docker_harness: DockerHarness) -> None:
    result = docker_harness.run(env_name="cachyos", module_failure=True)
    assert result.returncode != 0
    assert "failed to load the nf_tables kernel module" in result.stderr
    assert not any(event.startswith(("DAEMON_RELOAD", "ENABLE_USER", "DOCKER")) for event in docker_harness.events())


def test_cachyos_package_failures_and_missing_tools_stop_setup(docker_harness: DockerHarness) -> None:
    result = docker_harness.run(env_name="cachyos", package_failure="docker")
    assert result.returncode != 0
    assert not any(event.startswith(("DAEMON_RELOAD", "ENABLE_USER", "DOCKER")) for event in docker_harness.events())

    result = docker_harness.run(env_name="cachyos", missing_tool="dockerd-rootless.sh")
    assert result.returncode != 0
    assert f"{docker_harness.root}/home/bin/dockerd-rootless.sh is missing" in result.stderr
    assert not any(event.startswith(("DAEMON_RELOAD", "ENABLE_USER", "DOCKER")) for event in docker_harness.events())


@pytest.mark.parametrize("storage_driver", ["overlayfs", "overlay2", "fuse-overlayfs"])
def test_cachyos_supported_storage_drivers(docker_harness: DockerHarness, storage_driver: str) -> None:
    result = docker_harness.run(env_name="cachyos", storage_driver=storage_driver)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("failure", ["service", "endpoint", "security", "cgroup", "driver", "compose", "buildx"])
def test_cachyos_verification_failures_propagate(docker_harness: DockerHarness, failure: str) -> None:
    result = docker_harness.run(env_name="cachyos", verification_failure=failure)
    assert result.returncode != 0


def test_cachyos_environment_is_canonical_and_docker_variables_are_cleared(docker_harness: DockerHarness) -> None:
    runtime = docker_harness.root / "run/user/1000"
    result = docker_harness.run(
        env_name="cachyos",
        incoming_env={
            "XDG_RUNTIME_DIR": str(runtime),
            "XDG_CONFIG_HOME": "/hostile/config",
            "DOCKER_CONFIG": "/hostile/docker",
            "DOCKER_HOST": "tcp://hostile:2375",
            "DOCKER_CONTEXT": "hostile",
        },
    )
    assert result.returncode == 0, result.stderr
    docker_calls = "\n".join(event for event in docker_harness.events() if event.startswith("DOCKER"))
    assert "DOCKER_HOST=unset" in docker_calls and "DOCKER_CONTEXT=unset" in docker_calls
    assert f"XDG_CONFIG_HOME={docker_harness.root}/home/.config" in docker_calls
    assert f"DOCKER_CONFIG={docker_harness.root}/home/.docker" in docker_calls

    conflict = docker_harness.run(env_name="cachyos", incoming_env={"XDG_RUNTIME_DIR": "/wrong"})
    assert conflict.returncode != 0
    _barrier(docker_harness.events())
