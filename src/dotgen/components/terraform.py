from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_TERRAGRUNT_VERSION = "v0.96.1"
_TERRAGRUNT_SHA256 = {
    "amd64": "513eff2f87e2f5ec84369cc0f9d6c6766b43ca765fec4a3ac3598b933dc3218f",
    "arm64": "5cf6006c99b4d05e03eea1375cf8a591ade8b06a40e804b0b73f89f7589347c3",
}

_SETUP_DEBIAN = f"""\
install_packages ca-certificates curl gnupg
add_repo apt hashicorp "deb [signed-by=/etc/apt/keyrings/hashicorp.gpg] https://apt.releases.hashicorp.com trixie main" "https://apt.releases.hashicorp.com/gpg"
update_pkg_index
install_package terraform
_install_terragrunt_linux() {{
  local arch checksum
  case "$(detect_arch)" in
    x86_64) arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    *) error "unsupported arch for Terragrunt: $(detect_arch)"; return 1 ;;
  esac
  case "$arch" in
    amd64) checksum="{_TERRAGRUNT_SHA256["amd64"]}" ;;
    arm64) checksum="{_TERRAGRUNT_SHA256["arm64"]}" ;;
  esac
  download_bin_sha256 terragrunt \\
    "https://github.com/gruntwork-io/terragrunt/releases/download/{_TERRAGRUNT_VERSION}/terragrunt_linux_${{arch}}" \\
    "$checksum" "{_TERRAGRUNT_VERSION}" --version
}}
_install_terragrunt_linux
"""

_SETUP_BY_OS: dict[OS, str] = {
    OS.DEBIAN: _SETUP_DEBIAN,
    OS.MACOS: "add_repo tap hashicorp/tap\ninstall_package hashicorp/tap/terraform\ninstall_package terragrunt\n",
}


@dataclass(frozen=True)
class Terraform:
    name: str = "terraform"

    def applies_to(self, env: Environment) -> bool:
        return env.name in {"debian", "macos"}

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP_BY_OS[env.os])
