from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS

_AWS_CONFIG = """\
[default]
region = us-east-1
output = json
"""

_SETUP_MACOS = "install_package awscli\n"

_SETUP_LINUX = r"""install_package unzip
_install_awscli_linux() {
  local arch zip_arch tmp
  arch="$(detect_arch)"
  case "$arch" in
    x86_64) zip_arch=x86_64 ;;
    aarch64|arm64) zip_arch=aarch64 ;;
    *) error "unsupported arch for awscli: $arch"; return 1 ;;
  esac
  tmp="$(mktemp -d)"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${zip_arch}.zip" -o "$tmp/awscli.zip"
  unzip -q "$tmp/awscli.zip" -d "$tmp"
  sudo "$tmp/aws/install" --update
  rm -rf "$tmp"
}
if ! bin_exists aws; then
  _install_awscli_linux
fi
"""

_SETUP_BY_OS: dict[OS, str] = {
    OS.MACOS: _SETUP_MACOS,
    OS.DEBIAN: _SETUP_LINUX,
}

_BASHRC = """\
if bin_exists aws_completer; then
  complete -C "$(command -v aws_completer)" aws
fi
"""


@dataclass(frozen=True)
class Aws:
    name: str = "aws"

    def applies_to(self, env: Environment) -> bool:
        return env.os in _SETUP_BY_OS

    def render(self, env: Environment) -> Fragment:
        body = _SETUP_BY_OS[env.os] + 'install_config "$DIR/config/aws/config" "$HOME/.aws/config"\n'
        return Fragment(
            setup=body,
            bashrc=_BASHRC,
            configs=(ConfigFile(dest="aws/config", content=_AWS_CONFIG, mode=0o600),),
        )
