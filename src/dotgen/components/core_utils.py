from dataclasses import dataclass

from dotgen.bash import argv
from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_PACKAGES: dict[OS, tuple[str, ...]] = {
    OS.DEBIAN: (
        "git",
        "git-delta",
        "just",
        "jq",
        "yq",
        "fzf",
        "ripgrep",
        "fd-find",
        "eza",
        "bat",
        "tree",
        "vim",
        "htop",
        "btop",
        "cloc",
        "gnupg2",
        "bash-completion",
        "bsdmainutils",
        "protobuf-compiler",
    ),
    OS.MACOS: (
        "git",
        "git-delta",
        "just",
        "jq",
        "yq",
        "fzf",
        "ripgrep",
        "fd",
        "eza",
        "bat",
        "tree",
        "vim",
        "htop",
        "btop",
        "cloc",
        "gnupg",
        "bash-completion",
        "protobuf",
    ),
}

_CLI_SHIMS_DEBIAN = """\
if bin_exists fdfind && ! bin_exists fd; then
  link_file "$(command -v fdfind)" "$HOME/bin/fd"
fi
if bin_exists batcat && ! bin_exists bat; then
  link_file "$(command -v batcat)" "$HOME/bin/bat"
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
            body += _CLI_SHIMS_DEBIAN
        return Fragment(setup=body)
