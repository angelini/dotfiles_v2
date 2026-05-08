from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotgen.fragment import Fragment

if TYPE_CHECKING:
    from dotgen.environment import Environment

_SETUP = """\
install_script fnm https://fnm.vercel.app/install --skip-shell
"""

_BASHRC = """\
export PATH="$HOME/.local/share/fnm:$PATH"
if bin_exists fnm; then
  eval "$(fnm env --use-on-cd)"
fi
"""


@dataclass(frozen=True)
class NodeFnm:
    name: str = "node_fnm"

    def applies_to(self, env: "Environment") -> bool:
        return True

    def render(self, env: "Environment") -> Fragment:
        return Fragment(setup=_SETUP, bashrc=_BASHRC)
