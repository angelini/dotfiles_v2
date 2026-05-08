from __future__ import annotations

import os
import secrets
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


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
        return subprocess.run(argv, capture_output=True, text=True, check=check, timeout=timeout)

    def push(self, src: Path, dest: str) -> None:
        subprocess.run(
            ["orb", "push", "-m", self.name, str(src), dest],
            capture_output=True, text=True, check=True,
        )

    def assert_cmd(self, cmd: str, *, login: bool = False) -> None:
        result = self.run(cmd, login=login, check=False)
        if result.returncode != 0:
            raise AssertionError(
                f"command failed on vm={self.name} (exit {result.returncode}): {cmd}\n"
                f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
            )


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
