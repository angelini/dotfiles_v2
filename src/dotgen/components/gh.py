from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS

if TYPE_CHECKING:
    from dotgen.environment import Environment

_CONFIG = """\
git_protocol: ssh
prompt: enabled
aliases:
    co: pr checkout
"""

_DEB_LIST_LINE = (
    "deb [signed-by=/etc/apt/keyrings/githubcli.gpg] "
    "https://cli.github.com/packages stable main"
)
_DEB_KEY_URL = "https://cli.github.com/packages/githubcli-archive-keyring.gpg"

_SETUP_BY_OS: dict[OS, str] = {
    OS.MACOS: "install_package gh\n",
    OS.FEDORA: "install_package gh\n",
    OS.DEBIAN: (
        f'add_repo apt githubcli "{_DEB_LIST_LINE}" "{_DEB_KEY_URL}"\n'
        "update_pkg_index\n"
        "install_package gh\n"
    ),
}

_SETUP_TAIL = 'install_config "$DIR/config/gh/config.yml" "$HOME/.config/gh/config.yml"\n'


@dataclass(frozen=True)
class Gh:
    name: str = "gh"

    def applies_to(self, env: "Environment") -> bool:
        return True

    def render(self, env: "Environment") -> Fragment:
        body = _SETUP_BY_OS[env.os] + _SETUP_TAIL
        return Fragment(
            setup=body,
            configs=(ConfigFile(dest="gh/config.yml", content=_CONFIG),),
        )
