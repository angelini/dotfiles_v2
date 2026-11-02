from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_STRIPE_VERSION = "1.55.6"

_STRIPE_SETUP = f"""\
_install_stripe_linux() {{
  local arch checksum
  case "$(detect_arch)" in
    x86_64) arch=x86_64; checksum=1759a13a0c48f15e11979696df7b5958a73a8e6c1b92bea2a3ccb73ea97d5854 ;;
    aarch64|arm64) arch=arm64; checksum=a676e88cf1dd87351f9d7f907446b9d79ca832ff3b9ba1c178687923e7d05001 ;;
    *) error "unsupported arch for stripe: $(detect_arch)"; return 1 ;;
  esac
  download_tar_bin_sha256 stripe \\
    "https://github.com/stripe/stripe-cli/releases/download/v{_STRIPE_VERSION}/stripe_{_STRIPE_VERSION}_linux_${{arch}}.tar.gz" \\
    "$checksum" stripe "{_STRIPE_VERSION}" version
}}
_install_stripe_linux
"""


@dataclass(frozen=True)
class Stripe:
    name: str = "stripe"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup="install_package stripe-cli\n" if env.os is OS.MACOS else _STRIPE_SETUP)
