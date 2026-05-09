from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_SETUP_BY_OS: dict[OS, str] = {
    OS.MACOS: "install_cask font-ubuntu\ninstall_cask font-ubuntu-mono-nerd-font\n",
    OS.FEDORA: "install_package ubuntu-family-fonts\n",
}


@dataclass(frozen=True)
class Fonts:
    name: str = "fonts"

    def applies_to(self, env: Environment) -> bool:
        return env.os in _SETUP_BY_OS

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP_BY_OS[env.os])
