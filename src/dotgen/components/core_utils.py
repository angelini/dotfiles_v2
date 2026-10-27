from dataclasses import dataclass

from dotgen.bash import argv
from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_YQ_VERSION = "v4.54.1"
_YQ_RELEASE_BASE = f"https://github.com/mikefarah/yq/releases/download/{_YQ_VERSION}"
_YQ_ASSET_OS: dict[OS, str] = {
    OS.CACHYOS: "linux",
    OS.DEBIAN: "linux",
    OS.MACOS: "darwin",
}
_YQ_SHA256_LINUX = {
    "amd64": "8e34fc298390875de416e6a4afcb8cabeceb25d9aa8506c1a2f9353cf702ea5f",
    "arm64": "189088da0c6429ec5178dfaab1a114805f6cab0b61b165ab236efedf1d57a71b",
}
_YQ_SHA256: dict[OS, dict[str, str]] = {
    OS.CACHYOS: _YQ_SHA256_LINUX,
    OS.DEBIAN: _YQ_SHA256_LINUX,
    OS.MACOS: {
        "amd64": "3a812fce205a4d67014fb71b7fa297092210e580df3d8f52dddc2cf3a599c22b",
        "arm64": "fee511a181bd8b3e6b7da98842b41973bfac8cd3bcd341ed29a584620b5b2844",
    },
}

_PACKAGES: dict[OS, tuple[str, ...]] = {
    OS.CACHYOS: (
        "git",
        "curl",
        "git-delta",
        "just",
        "jq",
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
        "shelly",
    ),
    OS.DEBIAN: (
        "git",
        "git-delta",
        "just",
        "jq",
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


def _yq_setup(os: OS) -> str:
    asset_os = _YQ_ASSET_OS[os]
    checksums = _YQ_SHA256[os]
    return f"""\
_install_yq() {{
  local arch checksum
  case "$(detect_arch)" in
    x86_64) arch=amd64; checksum={checksums["amd64"]} ;;
    aarch64|arm64) arch=arm64; checksum={checksums["arm64"]} ;;
    *) error "unsupported arch for yq: $(detect_arch)"; return 1 ;;
  esac
  download_bin_sha256 yq "{_YQ_RELEASE_BASE}/yq_{asset_os}_${{arch}}" "$checksum" "{_YQ_VERSION}" --version
}}
_install_yq
"""


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
        body = argv("install_packages", *pkgs) + "\n" + _yq_setup(env.os)
        if env.os is OS.DEBIAN:
            body += _CLI_SHIMS_DEBIAN
        return Fragment(setup=body)
