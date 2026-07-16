from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_SETUP = "install_cask supacode\n"


@dataclass(frozen=True)
class Supacode:
    name: str = "supacode"

    def applies_to(self, env: Environment) -> bool:
        return env.os is OS.MACOS

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP)
