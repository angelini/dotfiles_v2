from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment

# Ensure macOS login shells read .bashrc
_BASH_PROFILE = '[ -r "$HOME/.bashrc" ] && source "$HOME/.bashrc"\n'
_PRIVATE_ALIAS_OVERLAY = '[ -r "${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/private-aliases.sh" ] && source "${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/private-aliases.sh"\n'

_SETUP = """\
install_config "$DIR/.bashrc" "$HOME/.bashrc"
install_config "$DIR/alias.sh" "$HOME/.aliases"
install_config "$DIR/config/bash/bash_profile" "$HOME/.bash_profile"
"""


@dataclass(frozen=True)
class DotfilesDeploy:
    name: str = "dotfiles_deploy"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP,
            alias=_PRIVATE_ALIAS_OVERLAY,
            configs=(ConfigFile(dest="bash/bash_profile", content=_BASH_PROFILE),),
        )
