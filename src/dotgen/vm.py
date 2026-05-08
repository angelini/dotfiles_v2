from __future__ import annotations

import os
import secrets
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


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
        head = (
            f"[vm {self.vm}] command timed out after {self.timeout}s"
            if self.returncode is None
            else f"[vm {self.vm}] command failed (exit {self.returncode})"
        )
        shell_note = " [login shell]" if self.login else ""
        return (
            f"\n{head}{shell_note}\n"
            f"$ {self.cmd}\n"
            f"\n{_stream_block('stdout', self.stdout)}"
            f"{_stream_block('stderr', self.stderr)}"
        )


def _stream_block(label: str, content: str) -> str:
    body = content if content else "(empty)"
    if not body.endswith("\n"):
        body += "\n"
    return f"--- {label} ({len(content)} bytes) ---\n{body}"


@dataclass(frozen=True)
class VmHandle:
    name: str
    user: str

    def run(
        self,
        cmd: str,
        *,
        login: bool = False,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        flag = "-lc" if login else "-c"
        argv = ["orb", "-m", self.name, "-u", self.user, "bash", flag, cmd]
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, check=False, timeout=timeout
            )
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
        subprocess.run(
            ["orb", "push", "-m", self.name, str(src), dest],
            capture_output=True, text=True, check=True,
        )

    def assert_cmd(self, cmd: str, *, login: bool = False) -> None:
        self.run(cmd, login=login, check=True)


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


@contextmanager
def vm_session(env_name: str, image: str) -> Iterator[VmHandle]:
    name = f"dotgen-test-{env_name}-{secrets.token_hex(4)}"
    user = os.environ["USER"]
    subprocess.run(["orb", "create", image, name], capture_output=True, text=True, check=True)
    try:
        yield VmHandle(name=name, user=user)
    finally:
        if os.environ.get("KEEP_VM") != "1":
            subprocess.run(["orb", "delete", "-f", name], capture_output=True, text=True, check=False)
