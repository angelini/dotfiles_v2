from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS


@dataclass(frozen=True)
class OrbStack:
    name: str = "orbstack"

    def applies_to(self, env: Environment) -> bool:
        return env.os is OS.MACOS

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup="install_cask orbstack\n")
