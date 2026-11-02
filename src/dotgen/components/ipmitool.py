from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment


@dataclass(frozen=True)
class Ipmitool:
    name: str = "ipmitool"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup="install_package ipmitool\n")
