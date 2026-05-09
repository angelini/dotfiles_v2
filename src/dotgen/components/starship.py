from dataclasses import dataclass

import tomli_w

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment

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

_DISABLED_MODULES: tuple[str, ...] = ("gcloud", "aws", "docker_context", "dotnet")

_TOML = tomli_w.dumps(
    {
        "format": "$directory$git_branch$git_status$kubernetes$character",
        "add_newline": False,
        "kubernetes": {
            "disabled": False,
            "format": "[$symbol$context( \\($namespace\\))]($style) ",
            "symbol": "⎈ ",
            "contexts": [{"context_pattern": ".*prod.*", "style": "bold red"}],
        },
        **{m: {"disabled": True} for m in _DISABLED_MODULES},
    }
)


@dataclass(frozen=True)
class Starship:
    name: str = "starship"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP,
            bashrc=_BASHRC,
            configs=(ConfigFile(dest="starship/starship.toml", content=_TOML),),
        )
