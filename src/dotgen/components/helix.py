from dataclasses import dataclass

import tomli_w

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS

_HELIX_CONFIG = tomli_w.dumps(
    {
        "theme": "default",
        "editor": {
            "line-number": "relative",
            "cursor-shape": {"insert": "bar"},
        },
    }
)

_BASHRC = """\
export EDITOR=hx
export VISUAL=hx
"""

_HELIX_VERSION = "25.07.1"

_XZ_PKG: dict[OS, str] = {OS.DEBIAN: "xz-utils"}


def _linux_setup(os: OS) -> str:
    return f"""\
_install_helix_linux() {{
  local tarch tmp dir
  case "$(detect_arch)" in
    x86_64) tarch=x86_64 ;;
    aarch64|arm64) tarch=aarch64 ;;
    *) error "unsupported arch for helix: $(detect_arch)"; return 1 ;;
  esac
  install_package {_XZ_PKG[os]}
  tmp="$(mktemp -d)"
  dir="helix-{_HELIX_VERSION}-${{tarch}}-linux"
  curl -fsSL "https://github.com/helix-editor/helix/releases/download/{_HELIX_VERSION}/${{dir}}.tar.xz" \\
    | tar -xJ -C "$tmp"
  ensure_dir "$HOME/bin"
  install -m 0755 "$tmp/$dir/hx" "$HOME/bin/hx"
  ensure_dir "$HOME/.config/helix"
  rm -rf "$HOME/.config/helix/runtime"
  cp -r "$tmp/$dir/runtime" "$HOME/.config/helix/runtime"
  rm -rf "$tmp"
}}
if ! bin_exists hx; then
  _install_helix_linux
fi
"""


_SETUP_TAIL = 'install_config "$DIR/config/helix/config.toml" "$HOME/.config/helix/config.toml"\n'


@dataclass(frozen=True)
class Helix:
    name: str = "helix"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        setup = "install_package helix\n" if env.os is OS.MACOS else _linux_setup(env.os)
        body = setup + _SETUP_TAIL
        return Fragment(
            setup=body,
            bashrc=_BASHRC,
            configs=(ConfigFile(dest="helix/config.toml", content=_HELIX_CONFIG),),
        )
