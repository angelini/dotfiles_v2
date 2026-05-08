from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotgen.bash import section
from dotgen.fragment import ConfigFile, Fragment

if TYPE_CHECKING:
    from dotgen.environment import Environment

_GITCONFIG = """\
[user]
    name = Alex Angelini
    email = alex.louis.angelini@gmail.com
[core]
    editor = hx
    excludesFile = ~/.gitignore_global
[push]
    default = current
[pull]
    ff = only
[diff]
    algorithm = patience
[init]
    defaultBranch = main
[url "ssh://git@github.com/"]
    insteadOf = https://github.com/
"""

_GITIGNORE_GLOBAL = """\
.DS_Store
__scratch__.*
CLAUDE.md
.serena/
.node-version
node_modules/
"""

_SETUP = """\
install_config "$DIR/config/git/gitconfig" "$HOME/.gitconfig"
install_config "$DIR/config/git/gitignore_global" "$HOME/.gitignore_global"
"""


@dataclass(frozen=True)
class GitSetup:
    name: str = "git_setup"

    def applies_to(self, env: "Environment") -> bool:
        return True

    def render(self, env: "Environment") -> Fragment:
        return Fragment(
            setup=section("git_setup", _SETUP),
            configs=(
                ConfigFile(dest="git/gitconfig", content=_GITCONFIG),
                ConfigFile(dest="git/gitignore_global", content=_GITIGNORE_GLOBAL),
            ),
        )
