from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS

_CONFIG = """\
font-family = UbuntuMonoNerdFont
font-size = 14
theme = default
window-decoration = true
audio-bell = false
"""

_GHOSTTY_DST = '"$HOME/Library/Application Support/com.mitchellh.ghostty/config"'

_SETUP = f'install_cask ghostty\ninstall_config "$DIR/config/ghostty/config" {_GHOSTTY_DST}\n'


@dataclass(frozen=True)
class Ghostty:
    name: str = "ghostty"

    def applies_to(self, env: Environment) -> bool:
        return env.os is OS.MACOS

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP,
            configs=(ConfigFile(dest="ghostty/config", content=_CONFIG),),
        )
