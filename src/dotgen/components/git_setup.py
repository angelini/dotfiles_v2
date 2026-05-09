from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment

_GITCONFIG = """\
[user]
    name = ${GIT_USER_NAME}
    email = ${GIT_USER_EMAIL}
    signingkey = ${GIT_SIGNING_KEY}
[commit]
    gpgsign = true
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
install_config_template "$DIR/config/git/gitconfig" "$HOME/.gitconfig" 'GIT_USER_NAME GIT_USER_EMAIL GIT_SIGNING_KEY'
install_config "$DIR/config/git/gitignore_global" "$HOME/.gitignore_global"
"""


@dataclass(frozen=True)
class GitSetup:
    name: str = "git_setup"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP,
            configs=(
                ConfigFile(dest="git/gitconfig", content=_GITCONFIG),
                ConfigFile(dest="git/gitignore_global", content=_GITIGNORE_GLOBAL),
            ),
            secrets=frozenset({"GIT_USER_NAME", "GIT_USER_EMAIL", "GIT_SIGNING_KEY"}),
        )
