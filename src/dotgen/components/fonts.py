from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_SETUP_DEBIAN = """install_packages fontconfig xz-utils
_install_nerd_fonts() {
  local tmp url
  tmp="$(mktemp -d)"
  url="https://github.com/ryanoasis/nerd-fonts/releases/download/v3.5.1/UbuntuMono.tar.xz"
  curl -fsSL "$url" -o "$tmp/fonts.tar.xz"
  mkdir -p "$HOME/.local/share/fonts"
  tar -xf "$tmp/fonts.tar.xz" -C "$HOME/.local/share/fonts"
  fc-cache -f
  rm -rf "$tmp"
}
if [ ! -d "$HOME/.local/share/fonts/UbuntuMono" ]; then
  _install_nerd_fonts
fi
"""

_SETUP_MACOS = """\
if [ ! -f "$HOME/Library/Fonts/Ubuntu-Regular.ttf" ]; then
  install_cask font-ubuntu
fi
if [ ! -f "$HOME/Library/Fonts/UbuntuMonoNerdFont-Regular.ttf" ]; then
  install_cask font-ubuntu-mono-nerd-font
fi
"""

_SETUP_BY_OS: dict[OS, str] = {
    OS.MACOS: _SETUP_MACOS,
    OS.DEBIAN: _SETUP_DEBIAN,
}


@dataclass(frozen=True)
class Fonts:
    name: str = "fonts"

    def applies_to(self, env: Environment) -> bool:
        return env.os in _SETUP_BY_OS

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP_BY_OS[env.os])
