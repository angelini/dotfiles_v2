from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment


@dataclass(frozen=True)
class Shellcheck:
    name: str = "shellcheck"

    def applies_to(self, env: Environment) -> bool:
        return env.name != "debian-docker"

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup="install_package shellcheck\n")
