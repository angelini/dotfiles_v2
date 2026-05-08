from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotgen.fragment import Fragment

if TYPE_CHECKING:
    from dotgen.environment import Environment

_SETUP = "install_package zoxide\n"

_BASHRC = """\
if bin_exists zoxide; then
  eval "$(zoxide init bash)"
fi
"""


@dataclass(frozen=True)
class Zoxide:
    name: str = "zoxide"

    def applies_to(self, env: "Environment") -> bool:
        return True

    def render(self, env: "Environment") -> Fragment:
        return Fragment(setup=_SETUP, bashrc=_BASHRC)
