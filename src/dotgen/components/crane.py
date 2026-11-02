from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS, EnvironmentRole

_CRANE_VERSION = "v0.22.1"

_CRANE_SETUP = f"""\
_install_crane_linux() {{
  local arch checksum
  case "$(detect_arch)" in
    x86_64) arch=x86_64; checksum=0ab7a1d6932a213aed964ce97666c3077fe691c8606413674a8b3e0b9ec4cda0 ;;
    aarch64|arm64) arch=arm64; checksum=898c0cff975f898a33e8c4580bdafb0e7c02c7faa33374e946762f97c4ab7110 ;;
    *) error "unsupported arch for crane: $(detect_arch)"; return 1 ;;
  esac
  download_tar_bin_sha256 crane \\
    "https://github.com/google/go-containerregistry/releases/download/{_CRANE_VERSION}/go-containerregistry_Linux_${{arch}}.tar.gz" \\
    "$checksum" crane "{_CRANE_VERSION.removeprefix("v")}" version
}}
_install_crane_linux
"""


@dataclass(frozen=True)
class Crane:
    name: str = "crane"

    def applies_to(self, env: Environment) -> bool:
        return env.role is not EnvironmentRole.CONTAINER

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_CRANE_SETUP if env.os is OS.DEBIAN else "install_package crane\n")
