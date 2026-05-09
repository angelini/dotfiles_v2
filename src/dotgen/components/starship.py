from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.starship_config import render_starship_toml

_SETUP = """\
ensure_dir "$HOME/.local/bin"
install_script starship https://starship.rs/install.sh -y -b "$HOME/.local/bin"
install_config "$DIR/config/starship/starship.toml" "$HOME/.config/starship.toml"
"""

_BASHRC = """\
if bin_exists starship; then
  eval "$(starship init bash)"
fi
"""


@dataclass(frozen=True)
class Starship:
    name: str = "starship"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP,
            bashrc=_BASHRC,
            configs=(ConfigFile(dest="starship/starship.toml", content=render_starship_toml()),),
        )
