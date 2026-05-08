from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotgen.fragment import Fragment

if TYPE_CHECKING:
    from dotgen.environment import Environment

_SETUP = """\
install_config "$DIR/.bashrc" "$HOME/.bashrc"
install_config "$DIR/alias.sh" "$HOME/.aliases"
"""


@dataclass(frozen=True)
class DotfilesDeploy:
    name: str = "dotfiles_deploy"

    def applies_to(self, env: "Environment") -> bool:
        return True

    def render(self, env: "Environment") -> Fragment:
        return Fragment(setup=_SETUP)
