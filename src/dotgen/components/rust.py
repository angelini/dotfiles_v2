from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotgen.bash import section
from dotgen.fragment import Fragment

if TYPE_CHECKING:
    from dotgen.environment import Environment

_SETUP = """\
install_script cargo https://sh.rustup.rs -y --default-toolchain stable
"""

_BASHRC = """\
# --- rust ---
[ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env"
"""


@dataclass(frozen=True)
class Rust:
    name: str = "rust"

    def applies_to(self, env: "Environment") -> bool:
        return True

    def render(self, env: "Environment") -> Fragment:
        return Fragment(setup=section("rust", _SETUP), bashrc=_BASHRC)
