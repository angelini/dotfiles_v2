from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment


@dataclass(frozen=True)
class Sshpass:
    name: str = "sshpass"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup="install_package sshpass\n")
