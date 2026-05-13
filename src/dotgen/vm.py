from __future__ import annotations

import contextlib
import os
import platform
import secrets
import shlex
import shutil
import subprocess
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class VmCommandError(AssertionError):
    def __init__(
        self,
        *,
        vm: str,
        cmd: str,
        returncode: int | None,
        stdout: str,
        stderr: str,
        login: bool = False,
        timeout: float | None = None,
    ) -> None:
        self.vm = vm
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.login = login
        self.timeout = timeout
        super().__init__(self._format())

    def _format(self) -> str:
        head = f"[vm {self.vm}] command timed out after {self.timeout}s" if self.returncode is None else f"[vm {self.vm}] command failed (exit {self.returncode})"
        shell_note = " [login shell]" if self.login else ""
        return f"\n{head}{shell_note}\n$ {self.cmd}\n\n{_stream_block('stdout', self.stdout)}{_stream_block('stderr', self.stderr)}"


class VmBackendUnavailable(RuntimeError):
    """Required tooling/host is missing for a backend; fixture should skip."""


def _stream_block(label: str, content: str) -> str:
    body = content if content else "(empty)"
    if not body.endswith("\n"):
        body += "\n"
    return f"--- {label} ({len(content)} bytes) ---\n{body}"


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


class _VmBackend(Protocol):
    label: str

    def is_available(self) -> tuple[bool, str]: ...
    def create(self, vm_name: str, image: str) -> str: ...
    def run(
        self,
        vm_name: str,
        user: str,
        cmd: str,
        *,
        login: bool,
        timeout: float | None,
    ) -> subprocess.CompletedProcess[str]: ...
    def push(self, vm_name: str, user: str, src: Path, dest: str) -> None: ...
    def teardown(self, vm_name: str) -> None: ...


class _OrbBackend:
    label = "orbstack"

    def is_available(self) -> tuple[bool, str]:
        if shutil.which("orb") is None:
            return False, "orb not on PATH"
        return True, ""

    def create(self, vm_name: str, image: str) -> str:
        _ = subprocess.run(["orb", "create", image, vm_name], capture_output=True, text=True, check=True)
        return os.environ["USER"]

    def run(
        self,
        vm_name: str,
        user: str,
        cmd: str,
        *,
        login: bool,
        timeout: float | None,
    ) -> subprocess.CompletedProcess[str]:
        flag = "-lc" if login else "-c"
        return subprocess.run(
            ["orb", "-m", vm_name, "-u", user, "bash", flag, cmd],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    def push(self, vm_name: str, user: str, src: Path, dest: str) -> None:
        _ = subprocess.run(
            ["orb", "push", "-m", vm_name, str(src), dest],
            capture_output=True,
            text=True,
            check=True,
        )

    def teardown(self, vm_name: str) -> None:
        _ = subprocess.run(["orb", "delete", "-f", vm_name], capture_output=True, text=True, check=False)


class _DockerBackend:
    label = "docker"

    def is_available(self) -> tuple[bool, str]:
        if shutil.which("docker") is None:
            return False, "docker not on PATH"
        try:
            _ = subprocess.run(["docker", "info"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False, "docker daemon not reachable"
        return True, ""

    def create(self, vm_name: str, image: str) -> str:
        # Build image from Dockerfile in the 'image' directory
        _ = subprocess.run(
            ["docker", "build", "-t", vm_name, image],
            capture_output=True,
            text=True,
            check=True,
        )
        # Keep container alive with tail
        _ = subprocess.run(
            ["docker", "run", "-d", "--name", vm_name, vm_name, "tail", "-f", "/dev/null"],
            capture_output=True,
            text=True,
            check=True,
        )
        return "alex"

    def run(
        self,
        vm_name: str,
        user: str,
        cmd: str,
        *,
        login: bool,
        timeout: float | None,
    ) -> subprocess.CompletedProcess[str]:
        # Wrap in bash -c as docker exec doesn't support -l
        bash_cmd = ["bash"]
        if login:
            bash_cmd.append("-lc")
        else:
            bash_cmd.append("-c")
        bash_cmd.append(cmd)

        return subprocess.run(
            ["docker", "exec", "-u", user, vm_name, *bash_cmd],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    def push(self, vm_name: str, user: str, src: Path, dest: str) -> None:
        _ = subprocess.run(
            ["docker", "cp", str(src), f"{vm_name}:{dest}"],
            capture_output=True,
            text=True,
            check=True,
        )
        # docker cp copies as root; fix ownership
        _ = subprocess.run(
            ["docker", "exec", "-u", "root", vm_name, "chown", "-R", f"{user}:{user}", dest],
            capture_output=True,
            text=True,
            check=True,
        )

    def teardown(self, vm_name: str) -> None:
        _ = subprocess.run(["docker", "rm", "-f", vm_name], capture_output=True, text=True, check=False)


_SSH_OPTS: tuple[str, ...] = (
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "LogLevel=ERROR",
    "-o",
    "ConnectTimeout=5",
)


@dataclass
class _TartSession:
    popen: subprocess.Popen[bytes]
    ip: str


class _TartBackend:
    label = "tart"
    _SSH_USER = "admin"
    _SSH_PASS = "admin"

    def __init__(self) -> None:
        self._sessions: dict[str, _TartSession] = {}

    def is_available(self) -> tuple[bool, str]:
        if platform.machine() != "arm64":
            return False, "tart requires Apple Silicon"
        for tool in ("tart", "sshpass"):
            if shutil.which(tool) is None:
                return False, f"{tool} not on PATH"
        return True, ""

    def create(self, vm_name: str, image: str) -> str:
        _ensure_tart_image_cached(image)
        _ = subprocess.run(["tart", "clone", image, vm_name], capture_output=True, text=True, check=True)
        popen = subprocess.Popen(
            ["tart", "run", "--no-graphics", vm_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            ip = self._wait_for_ip(vm_name, timeout=120)
            self._wait_for_ssh(ip, timeout=120)
        except Exception:
            popen.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                popen.wait(timeout=10)
            _ = subprocess.run(["tart", "stop", vm_name], capture_output=True, text=True, check=False)
            _ = subprocess.run(["tart", "delete", vm_name], capture_output=True, text=True, check=False)
            raise
        self._sessions[vm_name] = _TartSession(popen=popen, ip=ip)
        return self._SSH_USER

    def run(
        self,
        vm_name: str,
        user: str,
        cmd: str,
        *,
        login: bool,
        timeout: float | None,
    ) -> subprocess.CompletedProcess[str]:
        ip = self._sessions[vm_name].ip
        flag = "-lc" if login else "-c"
        argv = [
            "sshpass",
            "-p",
            self._SSH_PASS,
            "ssh",
            *_SSH_OPTS,
            f"{user}@{ip}",
            "bash",
            flag,
            shlex.quote(cmd),
        ]
        return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=timeout)

    def push(self, vm_name: str, user: str, src: Path, dest: str) -> None:
        ip = self._sessions[vm_name].ip
        argv = [
            "sshpass",
            "-p",
            self._SSH_PASS,
            "scp",
            *_SSH_OPTS,
            str(src),
            f"{user}@{ip}:{dest}",
        ]
        _ = subprocess.run(argv, capture_output=True, text=True, check=True)

    def teardown(self, vm_name: str) -> None:
        sess = self._sessions.pop(vm_name, None)
        if sess is not None:
            sess.popen.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                sess.popen.wait(timeout=10)
        _ = subprocess.run(["tart", "stop", vm_name], capture_output=True, text=True, check=False)
        _ = subprocess.run(["tart", "delete", vm_name], capture_output=True, text=True, check=False)

    def _wait_for_ip(self, vm_name: str, *, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = subprocess.run(["tart", "ip", vm_name], capture_output=True, text=True, check=False)
            ip = result.stdout.strip()
            if result.returncode == 0 and ip:
                return ip
            time.sleep(2)
        raise VmBackendUnavailable(f"tart vm {vm_name} did not acquire an IP within {timeout}s")

    def _wait_for_ssh(self, ip: str, *, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        argv = [
            "sshpass",
            "-p",
            self._SSH_PASS,
            "ssh",
            *_SSH_OPTS,
            f"{self._SSH_USER}@{ip}",
            "true",
        ]
        while time.monotonic() < deadline:
            result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=10)
            if result.returncode == 0:
                return
            time.sleep(2)
        raise VmBackendUnavailable(f"ssh to {ip} did not become reachable within {timeout}s")


def _ensure_tart_image_cached(image: str) -> None:
    if "@sha256:" not in image:
        raise VmBackendUnavailable(f"tart image must be digest-pinned (got {image!r}); see plans/06-macos-vm-integration.md for the bump procedure")
    host_repo, digest = image.split("@", 1)
    cache = Path.home() / ".tart" / "cache" / "OCIs" / host_repo / digest
    if not cache.exists():
        raise VmBackendUnavailable(f"tart image {image} not in local cache; run `tart pull {image}` first (~30 GB, one-time)")


@dataclass(frozen=True)
class VmHandle:
    name: str
    user: str
    backend: _VmBackend = field(repr=False)

    def run(
        self,
        cmd: str,
        *,
        login: bool = False,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = self.backend.run(self.name, self.user, cmd, login=login, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise VmCommandError(
                vm=self.name,
                cmd=cmd,
                returncode=None,
                stdout=_as_text(e.stdout),
                stderr=_as_text(e.stderr),
                login=login,
                timeout=timeout,
            ) from None
        if check and result.returncode != 0:
            raise VmCommandError(
                vm=self.name,
                cmd=cmd,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                login=login,
            )
        return result

    def push(self, src: Path, dest: str) -> None:
        self.backend.push(self.name, self.user, src, dest)

    def assert_cmd(self, cmd: str, *, login: bool = False) -> None:
        self.run(cmd, login=login, check=True)


_BACKENDS_BY_ENV: dict[str, type[_VmBackend]] = {
    "debian": _OrbBackend,
    "debian-docker": _DockerBackend,
    "macos": _TartBackend,
}


@contextmanager
def vm_session(env_name: str, image: str) -> Generator[VmHandle]:
    backend_cls = _BACKENDS_BY_ENV.get(env_name)
    if backend_cls is None:
        raise VmBackendUnavailable(f"no VM backend registered for env {env_name!r}")
    backend = backend_cls()
    ok, reason = backend.is_available()
    if not ok:
        raise VmBackendUnavailable(f"{env_name} backend ({backend.label}) unavailable: {reason}")
    vm_name = f"dotgen-test-{env_name}-{secrets.token_hex(4)}"
    user = backend.create(vm_name, image)
    try:
        yield VmHandle(name=vm_name, user=user, backend=backend)
    finally:
        if os.environ.get("KEEP_VM") != "1":
            backend.teardown(vm_name)
