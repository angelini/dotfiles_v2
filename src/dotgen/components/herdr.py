from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS

_VERSION = "0.8.2"
_RELEASE_BASE = f"https://github.com/herdrdev/herdr/releases/download/v{_VERSION}"
_BUN_INSTALL_URL = "https://bun.com/install"
_COLLIE_SOURCE = "AltanS/collie"
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
def _config(*, theme: str, manage_ssh_config: bool) -> str:
    remote = "\n[remote]\nmanage_ssh_config = true\n" if manage_ssh_config else ""
    return f"""\
onboarding = false

[theme]
name = "{theme}"

[ui.sidebar.spaces]
rows = [["state_icon", "workspace"], ["branch"]]

[ui.sound]
enabled = false

[update]
channel = "stable"
version_check = false
manifest_check = true
{remote}"""


_DEBIAN_CONFIG = _config(theme="catppuccin-latte", manage_ssh_config=True)
_LOCAL_CONFIG = _config(theme="catppuccin-latte", manage_ssh_config=False)
_REMOTE_CONFIG = _config(theme="rose-pine-dawn", manage_ssh_config=True)
_BASHRC = """\
export BUN_INSTALL="$HOME/.bun"
export PATH="$BUN_INSTALL/bin:$PATH"
"""

_LOCAL_LAUNCHER = r"""#!/usr/bin/env bash
set -euo pipefail

case "$#" in
  0) session=local ;;
  1)
    if [ -z "$1" ] || [[ "$1" = -* ]]; then
      printf 'usage: herd-local [session-name]\n' >&2
      exit 2
    fi
    session=$1
    ;;
  *)
    printf 'usage: herd-local [session-name]\n' >&2
    exit 2
    ;;
esac

herdr_bin="$HOME/.local/bin/herdr"
if [ ! -f "$herdr_bin" ] || [ ! -x "$herdr_bin" ]; then
  printf 'herd-local: managed Herdr binary is missing or invalid: %s\n' "$herdr_bin" >&2
  exit 1
fi

HERDR_CONFIG_PATH="${XDG_CONFIG_HOME:-$HOME/.config}/herdr/local.toml" \
  exec "$herdr_bin" --session "$session"
"""

_REMOTE_LAUNCHER = r"""#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ] || [[ "$1" = -* ]]; then
  printf 'usage: herd-remote <ssh-config-host>\n' >&2
  exit 2
fi

herdr_bin="$HOME/.local/bin/herdr"
if [ ! -f "$herdr_bin" ] || [ ! -x "$herdr_bin" ]; then
  printf 'herd-remote: managed Herdr binary is missing or invalid: %s\n' "$herdr_bin" >&2
  exit 1
fi

HERDR_CONFIG_PATH="${XDG_CONFIG_HOME:-$HOME/.config}/herdr/remote.toml" \
  exec "$herdr_bin" --remote "$1"
"""


def _setup(os: OS) -> str:
    asset_os = _ASSET_OS[os]
    checksums = _SHA256[os]
    if os is OS.MACOS:
        install = """\
  install_config "$DIR/config/herdr/local.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/local.toml"
  install_config "$DIR/config/herdr/remote.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/remote.toml"
  install -m 0755 "$DIR/config/herdr/herd-local" "$HOME/.local/bin/herd-local"
  install -m 0755 "$DIR/config/herdr/herd-remote" "$HOME/.local/bin/herd-remote"
"""
    else:
        install = """\
  install_config "$DIR/config/herdr/config.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/config.toml"
"""
    return f"""\
_install_herdr() {{
  local arch bun_path checksum remote_bin
  install_package unzip
  if [ ! -x "$HOME/.bun/bin/bun" ]; then
    BUN_INSTALL="$HOME/.bun" install_script bun "{_BUN_INSTALL_URL}"
  fi
  if [ -x "$HOME/.bun/bin/bun" ]; then
    bun_path="$HOME/.bun/bin"
  elif bin_exists bun; then
    bun_path="$(dirname "$(command -v bun)")"
  else
    error "Bun installer completed; bun unavailable"
    return 1
  fi
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
{install}  PATH="$bun_path:$PATH" "$remote_bin" plugin install "{_COLLIE_SOURCE}" --yes
}}
_install_herdr
"""


@dataclass(frozen=True)
class Herdr:
    name: str = "herdr"

    def applies_to(self, env: Environment) -> bool:
        return env.name in {"debian", "macos"}

    def render(self, env: Environment) -> Fragment:
        configs: list[ConfigFile] = []
        if env.os is OS.MACOS:
            configs.extend(
                (
                    ConfigFile(dest="herdr/local.toml", content=_LOCAL_CONFIG),
                    ConfigFile(dest="herdr/remote.toml", content=_REMOTE_CONFIG),
                    ConfigFile(dest="herdr/herd-local", content=_LOCAL_LAUNCHER, mode=0o755),
                    ConfigFile(dest="herdr/herd-remote", content=_REMOTE_LAUNCHER, mode=0o755),
                )
            )
        else:
            configs.append(ConfigFile(dest="herdr/config.toml", content=_DEBIAN_CONFIG))
        return Fragment(setup=_setup(env.os), bashrc=_BASHRC, configs=tuple(configs))
