from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment

_SETUP = """\
install_script uv https://astral.sh/uv/install.sh
"""

_BASHRC = """\
[ -f "$HOME/.local/bin/env" ] && source "$HOME/.local/bin/env"
"""


@dataclass(frozen=True)
class Uv:
    name: str = "uv"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP, bashrc=_BASHRC)
