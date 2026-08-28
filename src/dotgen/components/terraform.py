from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_TERRAGRUNT_VERSION = "v1.1.4"
_TERRAGRUNT_SHA256 = {
    "amd64": "a2640da8455fa5f3671167e6373832b0907b9dc972dd01c2093cc7808934e158",
    "arm64": "c65d1897446590ebb3c695835cc956c12c5374a9add8312517c83c9fd7a1c06b",
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
