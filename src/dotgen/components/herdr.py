from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS

_VERSION = "0.8.2"
_RELEASE_BASE = f"https://github.com/herdrdev/herdr/releases/download/v{_VERSION}"
_ASSET_OS: dict[OS, str] = {
    OS.DEBIAN: "linux",
    OS.MACOS: "macos",
}
_SHA256: dict[OS, dict[str, str]] = {
    OS.DEBIAN: {
        "x86_64": "976150a14d490c94b243ea2e1a7eb2dfb67f12e36b182db90936f6728e6aecf4",
        "aarch64": "f55610658e1c2e0d2aaef730b4b2ab885f7f8ba00285ab372bfb14f2e3d5b40d",
    },
    OS.MACOS: {
        "x86_64": "ab50262c8190cd7aa9056d249d255c08c328c3e8716de9cfa29db4f131b8e2c1",
        "aarch64": "a5d4f4d504d8b309c91f811050559300faba31258425f53c50852fc96f6ae574",
    },
}

_CONFIG = """\
onboarding = false

[theme]
name = "catppuccin-latte"

[ui.sidebar.spaces]
rows = [["state_icon", "workspace"], ["branch"]]

[ui.sound]
enabled = false

[update]
channel = "stable"
version_check = false
manifest_check = true

[remote]
manage_ssh_config = true
"""

_HELPER = r"""#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ] || [[ "$1" = -* ]]; then
  printf 'usage: herd-agent <ssh-config-host>\n' >&2
  exit 2
fi

herdr_bin="$HOME/.local/bin/herdr"
if [ ! -f "$herdr_bin" ] || [ ! -x "$herdr_bin" ]; then
  printf 'herd-agent: managed Herdr binary is missing or invalid: %s\n' "$herdr_bin" >&2
  exit 1
fi

exec "$herdr_bin" --remote "$1"
"""


def _setup(os: OS) -> str:
    asset_os = _ASSET_OS[os]
    checksums = _SHA256[os]
    return f"""\
_install_herdr() {{
  local arch checksum remote_bin
  case "$(detect_arch)" in
    x86_64) arch=x86_64; checksum={checksums["x86_64"]} ;;
    aarch64|arm64) arch=aarch64; checksum={checksums["aarch64"]} ;;
    *) error "unsupported arch for Herdr: $(detect_arch)"; return 1 ;;
  esac
  download_bin_sha256 herdr "{_RELEASE_BASE}/herdr-{asset_os}-${{arch}}" "$checksum" "{_VERSION}" --version
  ensure_dir "$HOME/.local/bin"
  remote_bin="$HOME/.local/bin/herdr"
  if [ -d "$remote_bin" ] || {{ [ -e "$remote_bin" ] && [ ! -f "$remote_bin" ] && [ ! -L "$remote_bin" ]; }}; then
    error "unsafe Herdr remote binary destination: $remote_bin"
    return 1
  fi
  link_file "$HOME/bin/herdr" "$remote_bin"
  if [ ! -f "$remote_bin" ] || [ ! -x "$remote_bin" ]; then
    error "failed to publish Herdr remote binary: $remote_bin"
    return 1
  fi
  install_config "$DIR/config/herdr/config.toml" "${{XDG_CONFIG_HOME:-$HOME/.config}}/herdr/config.toml"
  install -m 0755 "$DIR/config/herdr/herd-agent" "$HOME/.local/bin/herd-agent"
}}
_install_herdr
"""


@dataclass(frozen=True)
class Herdr:
    name: str = "herdr"

    def applies_to(self, env: Environment) -> bool:
        return env.name in {"debian", "macos"}

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_setup(env.os),
            configs=(
                ConfigFile(dest="herdr/config.toml", content=_CONFIG),
                ConfigFile(dest="herdr/herd-agent", content=_HELPER, mode=0o755),
            ),
        )
