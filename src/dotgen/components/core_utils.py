from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotgen.bash import argv, section
from dotgen.fragment import Fragment
from dotgen.types import OS

if TYPE_CHECKING:
    from dotgen.environment import Environment

_PACKAGES: dict[OS, tuple[str, ...]] = {
    OS.DEBIAN: (
        "jq",
        "ripgrep",
        "fd-find",
        "tree",
        "vim",
        "htop",
        "gnupg2",
        "bash-completion",
    ),
    OS.FEDORA: (
        "jq",
        "ripgrep",
        "fd-find",
        "tree",
        "vim",
        "htop",
        "gnupg2",
        "bash-completion",
    ),
    OS.MACOS: (
        "jq",
        "ripgrep",
        "fd",
        "tree",
        "vim",
        "htop",
        "gnupg",
        "bash-completion",
    ),
}

_FD_SHIM_DEBIAN = """\
ensure_dir "$HOME/bin"
if bin_exists fdfind && ! bin_exists fd; then
  ln -sf "$(command -v fdfind)" "$HOME/bin/fd"
fi
"""


@dataclass(frozen=True)
class CoreUtils:
    name: str = "core_utils"

    def applies_to(self, env: "Environment") -> bool:
        return True

    def render(self, env: "Environment") -> Fragment:
        pkgs = _PACKAGES[env.os]
        body = argv("install_packages", *pkgs) + "\n"
        if env.os is OS.DEBIAN:
            body += _FD_SHIM_DEBIAN
        return Fragment(setup=section("core_utils", body))
