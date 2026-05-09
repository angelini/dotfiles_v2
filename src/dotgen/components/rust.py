from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment

_SETUP = """\
install_script cargo https://sh.rustup.rs -y --default-toolchain stable
"""

_BASHRC = """\
[ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env"
"""


@dataclass(frozen=True)
class Rust:
    name: str = "rust"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP, bashrc=_BASHRC)
