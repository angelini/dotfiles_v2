from dataclasses import dataclass

from dotgen.bash import argv
from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_BUILD_DEPS: dict[OS, tuple[str, ...]] = {
    OS.DEBIAN: ("build-essential", "libssl-dev", "libffi-dev"),
    OS.MACOS: (),
}

_UV_INSTALL = """\
install_script uv https://astral.sh/uv/install.sh
"""

_BASHRC = """\
[ -f "$HOME/.local/bin/env" ] && source "$HOME/.local/bin/env"
"""


@dataclass(frozen=True)
class PythonTools:
    name: str = "python_tools"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        deps = _BUILD_DEPS[env.os]
        body = ""
        if deps:
            body += argv("install_packages", *deps) + "\n"
        body += _UV_INSTALL
        return Fragment(
            setup=body,
            bashrc=_BASHRC,
        )
