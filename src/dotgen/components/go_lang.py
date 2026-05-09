from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_PKG_BY_OS: dict[OS, str] = {
    OS.MACOS: "go",
    OS.FEDORA: "golang",
}

_BASHRC = """\
export GOPATH="$HOME/go"
export PATH="$GOPATH/bin:$PATH"
"""


@dataclass(frozen=True)
class GoLang:
    name: str = "go_lang"

    def applies_to(self, env: Environment) -> bool:
        return env.os in _PKG_BY_OS

    def render(self, env: Environment) -> Fragment:
        body = f"install_package {_PKG_BY_OS[env.os]}\n"
        return Fragment(setup=body, bashrc=_BASHRC)
