from dataclasses import dataclass
from typing import TYPE_CHECKING

import tomli_w

from dotgen.bash import section
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS

if TYPE_CHECKING:
    from dotgen.environment import Environment

_HELIX_CONFIG = tomli_w.dumps({
    "theme": "default",
    "editor": {
        "line-number": "relative",
        "cursor-shape": {"insert": "bar"},
    },
})

_BASHRC = """\
# --- helix ---
export EDITOR=hx
export VISUAL=hx
"""

_SETUP_BY_OS: dict[OS, str] = {
    OS.MACOS: 'install_package helix\n',
    OS.FEDORA: 'add_repo copr varlad/helix\ninstall_package helix\n',
    OS.DEBIAN: 'install_package helix\n',
}

_SETUP_TAIL = 'install_config "$DIR/config/helix/config.toml" "$HOME/.config/helix/config.toml"\n'


@dataclass(frozen=True)
class Helix:
    name: str = "helix"

    def applies_to(self, env: "Environment") -> bool:
        return True

    def render(self, env: "Environment") -> Fragment:
        body = _SETUP_BY_OS[env.os] + _SETUP_TAIL
        return Fragment(
            setup=section("helix", body),
            bashrc=_BASHRC,
            configs=(ConfigFile(dest="helix/config.toml", content=_HELIX_CONFIG),),
        )
