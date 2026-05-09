from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_DEPS_BY_OS: dict[OS, tuple[str, ...]] = {
    OS.MACOS: ("mercurial",),
    OS.FEDORA: ("curl", "git", "make", "bison", "gcc", "glibc-devel"),
}

_INSTALL_GVM = """\
if [ ! -s "$HOME/.gvm/scripts/gvm" ]; then
  install_script gvm https://raw.githubusercontent.com/moovweb/gvm/master/binscripts/gvm-installer
fi
"""

_BASHRC = """\
[ -s "$HOME/.gvm/scripts/gvm" ] && source "$HOME/.gvm/scripts/gvm"
export GOPATH="${GOPATH:-$HOME/go}"
export PATH="$GOPATH/bin:$PATH"
"""


@dataclass(frozen=True)
class GoLang:
    name: str = "go_lang"

    def applies_to(self, env: Environment) -> bool:
        return env.os in _DEPS_BY_OS

    def render(self, env: Environment) -> Fragment:
        deps = " ".join(_DEPS_BY_OS[env.os])
        body = f"install_packages {deps}\n{_INSTALL_GVM}"
        return Fragment(setup=body, bashrc=_BASHRC)
