from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment

_SETUP = """\
install_config "$DIR/.bashrc" "$HOME/.bashrc"
install_config "$DIR/alias.sh" "$HOME/.aliases"
"""


@dataclass(frozen=True)
class DotfilesDeploy:
    name: str = "dotfiles_deploy"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP)
