from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment

_SETUP = """\
install_package unzip
install_script fnm https://fnm.vercel.app/install --skip-shell --force-install --install-dir "$HOME/.local/share/fnm"
fnm_bin="$(command -v fnm 2>/dev/null || true)"
if [ -z "$fnm_bin" ]; then
  fnm_bin="$HOME/.local/share/fnm/fnm"
fi
if [ ! -x "$fnm_bin" ]; then
  error "fnm installer completed; fnm unavailable"
  exit 1
fi
eval "$("$fnm_bin" env --shell bash)"
"$fnm_bin" install --lts --use
"""

_BASHRC = """\
export PATH="$HOME/.local/share/fnm:$PATH"
if bin_exists fnm; then
  eval "$(fnm env --use-on-cd --shell bash)"
fi
"""


@dataclass(frozen=True)
class NodeFnm:
    name: str = "node_fnm"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP, bashrc=_BASHRC)
