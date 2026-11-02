from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_ATLAS_VERSION = "v0.36.0"
_ATLAS_SHA256 = {
    "darwin": {
        "amd64": "c8cbc5437db05405e9cd710dfa10bc9d392bfb67aaa160614fdd89a97054bac4",
        "arm64": "98fee6838472a9d2f90f91453449dae9a5acfdc12c36afefae67625fbf3f10fd",
    },
    "linux": {
        "amd64": "d88aae186a55e5893c318f3b11c838a3372adf4dac1e2fd3bc7d2b55944c5797",
        "arm64": "bb8a22a08ccd9a6cb93f0a16205b7bbeb067dd7fec1f60227c687d8de93d6088",
    },
}


def _atlas_setup(os: OS) -> str:
    asset_os = "darwin" if os is OS.MACOS else "linux"
    checksums = _ATLAS_SHA256[asset_os]
    # Homebrew installs the account-gated official build rather than the community build.
    return f"""\
_install_atlas() {{
  local arch checksum
  case "$(detect_arch)" in
    x86_64) arch=amd64; checksum={checksums["amd64"]} ;;
    aarch64|arm64) arch=arm64; checksum={checksums["arm64"]} ;;
    *) error "unsupported arch for atlas: $(detect_arch)"; return 1 ;;
  esac
  download_bin_sha256 atlas "https://release.ariga.io/atlas/atlas-{asset_os}-${{arch}}-{_ATLAS_VERSION}" "$checksum" "{_ATLAS_VERSION}" version
}}
_install_atlas
"""


@dataclass(frozen=True)
class Atlas:
    name: str = "atlas"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_atlas_setup(env.os))
