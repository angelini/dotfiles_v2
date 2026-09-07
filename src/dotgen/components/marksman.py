from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_VERSION = "2026-02-08"
_RELEASE_BASE = f"https://github.com/artempyanykh/marksman/releases/download/{_VERSION}"
_ASSET: dict[OS, dict[str, str]] = {
    OS.DEBIAN: {
        "x86_64": "marksman-linux-x64",
        "aarch64": "marksman-linux-arm64",
    },
    OS.MACOS: {
        "x86_64": "marksman-macos",
        "aarch64": "marksman-macos",
    },
}
_SHA256: dict[OS, dict[str, str]] = {
    OS.DEBIAN: {
        "x86_64": "be5098e8213219269c47fc0d916a66fa31ce0602ec967475c722260aabf26087",
        "aarch64": "db8e124527f7f8048e3e6c91821b9c52ef173d92c01e47d221bf1337afd962fb",
    },
    OS.MACOS: {
        "x86_64": "6a801c17b5ac0dba69787c5282b3b3bd416e66c96253fae098d311c6bbd1833b",
        "aarch64": "6a801c17b5ac0dba69787c5282b3b3bd416e66c96253fae098d311c6bbd1833b",
    },
}


def _setup(os: OS) -> str:
    assets = _ASSET[os]
    checksums = _SHA256[os]
    return f"""\
_install_marksman() {{
  local asset checksum
  case "$(detect_arch)" in
    x86_64) asset={assets["x86_64"]}; checksum={checksums["x86_64"]} ;;
    aarch64|arm64) asset={assets["aarch64"]}; checksum={checksums["aarch64"]} ;;
    *) error "unsupported arch for Marksman: $(detect_arch)"; return 1 ;;
  esac
  download_bin_sha256 marksman "{_RELEASE_BASE}/${{asset}}" "$checksum" "{_VERSION}" --version
}}
_install_marksman
"""


@dataclass(frozen=True)
class Marksman:
    name: str = "marksman"

    def applies_to(self, env: Environment) -> bool:
        return env.name in {"debian", "macos"}

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_setup(env.os))
