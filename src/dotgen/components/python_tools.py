from dataclasses import dataclass

from dotgen.bash import argv
from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_BUILD_DEPS: dict[OS, tuple[str, ...]] = {
    OS.DEBIAN: ("build-essential", "libssl-dev", "libffi-dev"),
    OS.MACOS: (),
}

_INSTALL = """\
uv_bin="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"
if [ ! -x "$uv_bin" ]; then
  error "python_tools: uv not found"
  exit 1
fi
"$uv_bin" tool install python-lsp-server
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
        body += _INSTALL
        return Fragment(setup=body)
