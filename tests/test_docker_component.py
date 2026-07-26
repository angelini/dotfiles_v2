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
        mode: str = "deploy",
        *,
        os_release: str = "ID=debian\nVERSION_ID=13\nVERSION_CODENAME=trixie\n",
        arch: str = "amd64",
        subuid: str = _VALID_SUBIDS,
        subgid: str = _VALID_SUBIDS,
        marker_state: str = "none",
        package_failure: str | None = None,
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
        (root / "etc/os-release").write_text(os_release)
        (root / "etc/subuid").write_text(subuid)
        (root / "etc/subgid").write_text(subgid)
        if cgroup:
            (root / "sys/fs/cgroup/cgroup.controllers").write_text("cpu\n")
        runtime = root / "run/user/1000"
        runtime.mkdir(parents=True, exist_ok=True)
        if ready_after == 0 and not (runtime / "bus").exists():
            self._socket(runtime / "bus")
        if marker_state in {"both", "unit"}:
            marker = home / ".config/systemd/user/docker.service"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
        if marker_state in {"both", "context"}:
            marker = home / ".docker/contexts/meta/12b961af5feb3e9d39f93b2cefb9a1a944f18d02cca0cac2f04f5a982240605f/meta.json"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
        if root_socket == "stale":
            (root / "var/run").mkdir(parents=True, exist_ok=True)
            (root / "var/run/docker.sock").write_text("stale")
        if root_socket == "live":
            self._socket(root / "var/run/docker.sock")

        setup = Docker().render(ENVIRONMENTS["debian"]).setup
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
            id)
  case "${1:-}" in
  -un) [ "$ACCOUNT" = name ] && echo Alice || echo alice ;;
  -u|-g) [ "$ACCOUNT" = zero ] && echo 0 || echo 1000 ;;
  *) echo 1000 ;;
  esac ;;
            getent) [ "$ACCOUNT" = missing ] && exit 2; [ "$ACCOUNT" = mismatch ] && echo "alice:x:999:1000::${HOME}:/bin/bash" || echo "alice:x:1000:1000::${HOME}:/bin/bash" ;;
            stat) [ "$2" = "%u" ] && echo "$RUNTIME_OWNER" || echo "$RUNTIME_MODE" ;;
            ss) [ "$ROOT_SOCKET" = live ] && echo "u_str LISTEN 0 0 $ROOT/var/run/docker.sock" ;;
            sleep) log WAIT; n=$(cat "$STATE/waits" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$STATE/waits"; if [ "$n" = "$READY_AFTER" ]; then socket "$ROOT/run/user/1000/bus"; fi ;;
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
                case "${1:-}" in show-environment) [ -S "$ROOT/run/user/1000/bus" ] ;; enable) log "ENABLE_USER $*"; socket "$ROOT/run/user/1000/docker.sock" ;; esac
              elif [ "${1:-}" = is-enabled ]; then unit="${@: -1}"; cat "$STATE/$unit.enabled" 2>/dev/null || echo disabled
              elif [ "${1:-}" = is-active ]; then
                case "${*: -1}" in
                systemd-logind.service) [ "$LOGIND" = 1 ] ;;
                user@*) [ "$(cat "$STATE/user.active" 2>/dev/null || echo inactive)" = active ] ;;
                *) [ "$(cat "$STATE/${*: -1}.active" 2>/dev/null || echo inactive)" = active ] ;;
                esac
              elif [ "${1:-}" = show ]; then echo "$SYSTEM_STATE"
              elif [ "${1:-}" = start ]; then echo active > "$STATE/user.active"
              elif [ "${1:-}" = status ]; then echo user-unit-diagnostic >&2
              fi ;;
            dockerd-rootless-setuptool.sh)
  log "SETUP DOCKER_HOST=${DOCKER_HOST-unset} DOCKER_CONTEXT=${DOCKER_CONTEXT-unset} XDG_CONFIG_HOME=${XDG_CONFIG_HOME-unset} DOCKER_CONFIG=${DOCKER_CONFIG-unset}"
  mkdir -p "$HOME/.config/systemd/user" "$HOME/.docker/contexts/meta/12b961af5feb3e9d39f93b2cefb9a1a944f18d02cca0cac2f04f5a982240605f"
  : > "$HOME/.config/systemd/user/docker.service"
  : > "$HOME/.docker/contexts/meta/12b961af5feb3e9d39f93b2cefb9a1a944f18d02cca0cac2f04f5a982240605f/meta.json" ;;
            docker)
  log "DOCKER $* DOCKER_HOST=${DOCKER_HOST-unset} DOCKER_CONTEXT=${DOCKER_CONTEXT-unset} XDG_CONFIG_HOME=${XDG_CONFIG_HOME-unset} DOCKER_CONFIG=${DOCKER_CONFIG-unset}"
  case "${1:-}" in
  context) case "${2:-}" in inspect) echo "unix://$ROOT/run/user/1000/docker.sock" ;; esac ;;
  info) [[ "$*" = *SecurityOptions* ]] && echo '["rootless"]' || echo 2 ;;
  esac ;;
            esac
            """
        )
        command = fake / "command"
        command.write_text(dispatcher)
        command.chmod(0o755)
        for name in ("ps", "dpkg", "id", "getent", "stat", "ss", "sleep", "loginctl", "systemctl", "docker", "dockerd-rootless-setuptool.sh", "newuidmap", "newgidmap", "getsubids"):
            link = fake / name
            if not link.exists():
                link.symlink_to(command.name)
        prelude = textwrap.dedent(
            """set -u
            error() { printf '%s\n' "$*" >&2; }
            bin_exists() { command -v "$1" >/dev/null; }
            sudo() { echo "SUDO $*" >> "$STATE/events"; while [[ "${1:-}" = *=* ]]; do shift; done; "$@"; }
            install_package() { [ "$DOTGEN_MODE" = diff ] && { echo "REPORT INSTALL $1" >> "$STATE/events"; return; }; echo "INSTALL $1" >> "$STATE/events"; }
            install_packages() { [ "$DOTGEN_MODE" = diff ] && { echo "REPORT INSTALLS" >> "$STATE/events"; return; }; echo "INSTALLS $*" >> "$STATE/events"; [ -z "$PACKAGE_FAILURE" ] || return 1; }
            add_repo() { [ "$DOTGEN_MODE" = diff ] && { echo "REPORT ADD_REPO" >> "$STATE/events"; return; }; echo "ADD_REPO" >> "$STATE/events"; }
            remove_packages() { [ "$DOTGEN_MODE" = diff ] && { echo "REPORT REMOVE" >> "$STATE/events"; return; }; echo "REMOVE" >> "$STATE/events"; }
            update_pkg_index() { [ "$DOTGEN_MODE" = diff ] && { echo "REPORT UPDATE_INDEX" >> "$STATE/events"; return; }; echo "UPDATE_INDEX" >> "$STATE/events"; }
            service_mask() {
              [ "$DOTGEN_MODE" = diff ] && { echo "REPORT MASK $*" >> "$STATE/events"; return; }
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
        env = os.environ | {
            "PATH": f"{fake}:{os.environ['PATH']}",
            "DOTGEN_MODE": mode,
            "STATE": str(state),
            "ROOT": str(root),
            "HOME": str(home),
            "ARCH": arch,
            "ROOT_SOCKET": root_socket,
            "RUNTIME_PATH": str(runtime) if runtime_path == "canonical" else runtime_path,
            "RUNTIME_MODE": runtime_mode,
            "RUNTIME_OWNER": runtime_owner,
            "READY_AFTER": str(ready_after),
            "PACKAGE_FAILURE": package_failure or "",
            "SYSTEMD": "1" if systemd else "0",
            "LOGIND": "1" if logind else "0",
            "SYSTEM_STATE": "running",
            "ACCOUNT": account,
        }
        if incoming_env:
            env.update(incoming_env)
        return subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)


@pytest.fixture
def docker_harness() -> Iterator[DockerHarness]:
    with tempfile.TemporaryDirectory(prefix="dotgen-docker-", dir="/tmp") as temp_dir:
        yield DockerHarness(Path(temp_dir) / "root")


def _barrier(events: list[str]) -> None:
    assert not any(event.startswith(("MASK", "REMOVE", "ADD_REPO", "UPDATE_INDEX", "INSTALLS docker-ce")) for event in events)


def test_docker_setup_is_bash_syntax_clean(tmp_path: Path) -> None:
    script = tmp_path / "docker.sh"
    script.write_text(Docker().render(ENVIRONMENTS["debian"]).setup)
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
    remove_index = next(i for i, event in enumerate(events) if event == "REMOVE")
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


def test_diff_runtime_readiness_and_environment_resistance(docker_harness: DockerHarness) -> None:
    assert docker_harness.run(mode="diff").returncode == 0
    before = {str(path.relative_to(docker_harness.root)): path.read_bytes() for path in docker_harness.root.rglob("*") if path.is_file() and path.name not in {"run.sh", "setup.sh", "events"}}
    result = docker_harness.run(mode="diff", reset=False)
    assert result.returncode == 0, result.stderr
    assert all(event.startswith(("REPORT", "SYSTEMCTL")) for event in docker_harness.events())
    after = {str(path.relative_to(docker_harness.root)): path.read_bytes() for path in docker_harness.root.rglob("*") if path.is_file() and path.name not in {"run.sh", "setup.sh", "events"}}
    assert not any(event.startswith(("SUDO", "LOGINCTL", "SETUP", "DOCKER")) for event in docker_harness.events())
    assert after == before
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
