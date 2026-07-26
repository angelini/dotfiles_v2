from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment

_NPMRC = """\
//npm.pkg.github.com/:_authToken=${NPM_TOKEN}
@qawolf:registry=https://npm.pkg.github.com
"""

_SETUP = """\
install_config_template "$DIR/config/npm/npmrc" "$HOME/.npmrc" 'NPM_TOKEN' 0600
"""


@dataclass(frozen=True)
class NpmConfig:
    name: str = "npm_config"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP,
            configs=(ConfigFile(dest="npm/npmrc", content=_NPMRC, mode=0o600),),
            secrets=frozenset({"NPM_TOKEN"}),
        )
