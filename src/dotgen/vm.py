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
    def prepare_passwordless_sudo(self, vm_name: str, user: str) -> subprocess.CompletedProcess[str]: ...
    def prepare_rootless_container_subids(self, vm_name: str, user: str) -> subprocess.CompletedProcess[str]: ...
    def teardown(self, vm_name: str) -> None: ...


_PREPARE_PASSWORDLESS_SUDO = r"""set -euo pipefail
user="$1"
[[ "$user" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || { echo "invalid account" >&2; exit 1; }
id "$user" >/dev/null 2>&1 || { echo "unknown account" >&2; exit 1; }
sudoers_dir=/etc/sudoers.d
rule="$sudoers_dir/dotgen-vm-test"
mkdir -p "$sudoers_dir"
tmp="$(mktemp "$sudoers_dir/.dotgen-vm-test.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
printf 'Defaults:%s !authenticate\n%s ALL=(ALL) NOPASSWD: ALL\n' "$user" "$user" > "$tmp"
chmod 0440 "$tmp"
visudo -cf "$tmp" >/dev/null
mv -f "$tmp" "$rule"
trap - EXIT
visudo -cf /etc/sudoers >/dev/null
"""


_ORB_PREPARE_ROOTLESS_SUBIDS = r"""set -euo pipefail
user="$1"
[[ "$user" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || { echo "invalid account" >&2; exit 1; }
record="$(getent passwd "$user")" || { echo "unknown account" >&2; exit 1; }
IFS=: read -r record_user _ record_uid record_gid _ _ <<< "$record"
[[ "$record_uid" =~ ^[1-9][0-9]*$ && "$record_gid" =~ ^[1-9][0-9]*$ ]] && [ "$record_user" = "$user" ] || { echo "invalid account record" >&2; exit 1; }
[ "$(id -u "$user")" = "$record_uid" ] || { echo "account UID mismatch" >&2; exit 1; }

read_limit() {
  local key="$1" count value
  count="$(grep -Ec "^[[:space:]]*$key[[:space:]]+[0-9]+[[:space:]]*(#.*)?$" /etc/login.defs || true)"
  [ "$count" = 1 ] || { echo "missing or duplicate $key" >&2; return 1; }
  value="$(awk -v key="$key" '$1 == key { print $2 }' /etc/login.defs)"
  [[ "$value" =~ ^[0-9]+$ ]] || return 1
  printf '%s' "$value"
}
uid_min="$(read_limit SUB_UID_MIN)"; uid_max="$(read_limit SUB_UID_MAX)"
gid_min="$(read_limit SUB_GID_MIN)"; gid_max="$(read_limit SUB_GID_MAX)"
for pair in "$uid_min:$uid_max" "$gid_min:$gid_max"; do
  IFS=: read -r min max <<< "$pair"
  [ "$min" -le "$max" ] && [ "$max" -le 4294967295 ] && [ $((max - min + 1)) -ge 65536 ] || { echo "invalid subordinate-ID bounds" >&2; exit 1; }
done

validate_file() {
  local file="$1"
  awk -F: '
    /^[[:space:]]*$/ || /^[[:space:]]*#/ { next }
    NF != 3 || $1 == "" || $2 !~ /^[0-9]+$/ || $3 !~ /^[0-9]+$/ { exit 1 }
    { start=$2+0; count=$3+0; end=start+count-1; if (start > 4294967295 || count < 1 || count > 4294967295 || end > 4294967295) exit 1 }
  ' "$file" || { echo "invalid allocation record in $file" >&2; return 1; }
}

choose_range() {
  local file="$1" min="$2" max="$3" numeric="$4" user_count numeric_count selected candidate start range_count end
  validate_file "$file" || return 1
  user_count="$(awk -F: -v user="$user" '$1 == user { count++ } END { print count + 0 }' "$file")"
  numeric_count="$(awk -F: -v numeric="$numeric" '$1 == numeric { count++ } END { print count + 0 }' "$file")"
  if [ "$user_count" -gt 0 ] && [ "$numeric_count" -gt 0 ]; then
    echo "both username and numeric-principal ranges exist in $file" >&2; return 1
  fi
  if [ "$user_count" -gt 1 ] || [ "$numeric_count" -gt 1 ]; then
    echo "multiple account ranges in $file" >&2; return 1
  fi
  if [ "$user_count" = 1 ] || [ "$numeric_count" = 1 ]; then
    selected="$(awk -F: -v user="$user" -v numeric="$numeric" '$1 == user || $1 == numeric { print $1 ":" $2 ":" $3 }' "$file")"
    IFS=: read -r principal start range_count <<< "$selected"
    [ "$range_count" -ge 65536 ] || { echo "short existing range in $file" >&2; return 1; }
    end=$((start + range_count - 1))
    if [ "$start" -le "$numeric" ] && [ "$numeric" -le "$end" ]; then
      echo "account range contains host ID in $file" >&2; return 1
    fi
    if awk -F: -v user="$user" -v numeric="$numeric" -v selected_start="$start" -v selected_count="$range_count" '
      BEGIN { selected_end = selected_start + selected_count - 1 }
      /^[[:space:]]*$/ || /^[[:space:]]*#/ { next }
      $1 != user && $1 != numeric && selected_start <= $2 + $3 - 1 && $2 <= selected_end { exit 1 }
    ' "$file"; then :; else
      echo "account range overlaps foreign allocation in $file" >&2; return 1
    fi
    printf '%s:%s:%s' "$principal" "$start" "$range_count"
    return 0
  fi
  candidate="$min"
  while IFS=: read -r start range_count; do
    [ -n "$start" ] || continue
    end=$((start + range_count - 1))
    if [ "$candidate" -le "$end" ] && [ $((candidate + 65535)) -ge "$start" ]; then candidate=$((end + 1)); fi
  done < <({ awk -F: '/^[[:space:]]*$/ || /^[[:space:]]*#/ { next } { print $2 ":" $3 }' "$file"; printf '%s:1\n' "$numeric"; } | sort -t: -k1,1n)
  [ "$candidate" -le "$max" ] && [ $((candidate + 65535)) -le "$max" ] || { echo "no available subordinate-ID range" >&2; return 1; }
  printf ':%s:65536' "$candidate"
}

uid_range="$(choose_range /etc/subuid "$uid_min" "$uid_max" "$record_uid")"
gid_range="$(choose_range /etc/subgid "$gid_min" "$gid_max" "$record_gid")"
IFS=: read -r uid_principal uid_start uid_count <<< "$uid_range"
IFS=: read -r gid_principal gid_start gid_count <<< "$gid_range"
uid_end=$((uid_start + uid_count - 1)); gid_end=$((gid_start + gid_count - 1))
added_uid=0; added_gid=0
rollback() {
  status=$?
  if [ "$status" -ne 0 ]; then
    [ "$added_gid" = 0 ] || usermod --del-subgids "$gid_start-$gid_end" "$user" || true
    [ "$added_uid" = 0 ] || usermod --del-subuids "$uid_start-$uid_end" "$user" || true
  fi
  exit "$status"
}
trap rollback EXIT
[ -n "$uid_principal" ] || { usermod --add-subuids "$uid_start-$uid_end" "$user"; added_uid=1; }
[ -n "$gid_principal" ] || { usermod --add-subgids "$gid_start-$gid_end" "$user"; added_gid=1; }
verified_uid="$(choose_range /etc/subuid "$uid_min" "$uid_max" "$record_uid")"
verified_gid="$(choose_range /etc/subgid "$gid_min" "$gid_max" "$record_gid")"
[ -n "$uid_principal" ] || uid_range="$user:$uid_start:$uid_count"
[ -n "$gid_principal" ] || gid_range="$user:$gid_start:$gid_count"
[ "$verified_uid" = "$uid_range" ] && [ "$verified_gid" = "$gid_range" ] || { echo "subordinate-ID final verification failed" >&2; exit 1; }
trap - EXIT
"""


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
        with src.open("rb") as stdin:
            _ = subprocess.run(
                ["orb", "-m", vm_name, "-u", user, "sh", "-c", 'cat > "$1"', "sh", dest],
                stdin=stdin,
                capture_output=True,
                check=True,
            )

    def prepare_passwordless_sudo(self, vm_name: str, user: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["orb", "-m", vm_name, "-u", "root", "bash", "-s", "--", user],
            input=_PREPARE_PASSWORDLESS_SUDO,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def prepare_rootless_container_subids(self, vm_name: str, user: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["orb", "-m", vm_name, "-u", "root", "bash", "-s", "--", user],
            input=_ORB_PREPARE_ROOTLESS_SUBIDS,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
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

    def prepare_passwordless_sudo(self, vm_name: str, user: str) -> subprocess.CompletedProcess[str]:
        _ = (vm_name, user)
        raise VmBackendUnavailable("passwordless sudo is already provisioned in the Docker fixture")

    def prepare_rootless_container_subids(self, vm_name: str, user: str) -> subprocess.CompletedProcess[str]:
        _ = (vm_name, user)
        raise VmBackendUnavailable("rootless-container subordinate-ID preparation is supported only by the OrbStack Debian fixture")

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

    def prepare_passwordless_sudo(self, vm_name: str, user: str) -> subprocess.CompletedProcess[str]:
        ip = self._sessions[vm_name].ip
        cmd = f"sudo -S -p '' bash -c {shlex.quote(_PREPARE_PASSWORDLESS_SUDO)} -- {shlex.quote(user)}"
        argv = [
            "sshpass",
            "-p",
            self._SSH_PASS,
            "ssh",
            *_SSH_OPTS,
            f"{user}@{ip}",
            cmd,
        ]
        return subprocess.run(
            argv,
            input=f"{self._SSH_PASS}\n",
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def prepare_rootless_container_subids(self, vm_name: str, user: str) -> subprocess.CompletedProcess[str]:
        _ = (vm_name, user)
        raise VmBackendUnavailable("rootless-container subordinate-ID preparation is supported only by the OrbStack Debian fixture")

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

    def prepare_passwordless_sudo(self) -> None:
        result = self.backend.prepare_passwordless_sudo(self.name, self.user)
        if result.returncode != 0:
            raise VmCommandError(
                vm=self.name,
                cmd="prepare passwordless sudo",
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        self.run("sudo -n -v", timeout=30)

    def prepare_rootless_container_subids(self) -> None:
        result = self.backend.prepare_rootless_container_subids(self.name, self.user)
        if result.returncode != 0:
            raise VmCommandError(
                vm=self.name,
                cmd="prepare rootless-container subordinate IDs",
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )


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
