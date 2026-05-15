from dataclasses import dataclass

from dotgen.bash import argv
from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_PACKAGES: dict[OS, tuple[str, ...]] = {
    OS.DEBIAN: (
        "git",
        "jq",
        "yq",
        "fzf",
        "ripgrep",
        "fd-find",
        "tree",
        "vim",
        "htop",
        "cloc",
        "gnupg2",
        "bash-completion",
        "bsdmainutils",
    ),
    OS.MACOS: (
        "git",
        "jq",
        "yq",
        "fzf",
        "ripgrep",
        "fd",
        "tree",
        "vim",
        "htop",
        "cloc",
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

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        pkgs = _PACKAGES[env.os]
        body = argv("install_packages", *pkgs) + "\n"
        if env.os is OS.DEBIAN:
            body += _FD_SHIM_DEBIAN
        return Fragment(setup=body)
