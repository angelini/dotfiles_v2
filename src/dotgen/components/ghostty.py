from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS, EnvironmentRole

_CONFIG = """\
theme = Tomorrow
background-opacity = 1
background-blur = false
shell-integration = bash
working-directory = home
window-inherit-working-directory = false
tab-inherit-working-directory = false
scrollback-limit = 100_000_000
unfocused-split-opacity = 1
bell-features = no-audio, no-system, no-attention, no-title
shell-integration-features = ssh-env,ssh-terminfo
keybind = shift+enter=text:\\x0a
"""

_SETUP_BY_OS: dict[OS, str] = {
    OS.CACHYOS: (
        "install_package ghostty\n"
        'if ! bin_exists ghostty; then error "Ghostty package installed without ghostty CLI"; exit 1; fi\n'
        'install_config "$DIR/config/ghostty/config" "${XDG_CONFIG_HOME:-$HOME/.config}/ghostty/config"\n'
    ),
    OS.MACOS: 'install_cask ghostty\ninstall_config "$DIR/config/ghostty/config" "$HOME/Library/Application Support/com.mitchellh.ghostty/config"\n',
}


@dataclass(frozen=True)
class Ghostty:
    name: str = "ghostty"

    def applies_to(self, env: Environment) -> bool:
        return env.role is EnvironmentRole.WORKSTATION and env.os in _SETUP_BY_OS

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP_BY_OS[env.os],
            configs=(ConfigFile(dest="ghostty/config", content=_CONFIG),),
        )
