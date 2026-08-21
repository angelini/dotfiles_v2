from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_VERSION = "0.10.0"
_RELEASE_BASE = f"https://github.com/tamasfe/taplo/releases/download/{_VERSION}"
_ASSET_OS: dict[OS, str] = {
    OS.DEBIAN: "linux",
    OS.MACOS: "darwin",
}
_SHA256: dict[OS, dict[str, str]] = {
    OS.DEBIAN: {
        "x86_64": "dad2faf6377d2daa4f4fabf459fe7ccfb98a5448f0d4bca8270ca9acb0409bfe",
        "aarch64": "82df9d765856d0d94d2147cc0912016e4a2bfb96cbe947347b7cc04c7f4431ba",
    },
    OS.MACOS: {
        "x86_64": "9fd7a2872ea154df61a2c7e9ca69fc19ac08e29f2e2dc2f866e299bdc789c1a1",
        "aarch64": "13cd257c1cadb003b40daf82b3fb1451e012e2463b760bdd33df07a07970c604",
    },
}


def _setup(os: OS) -> str:
    asset_os = _ASSET_OS[os]
    checksums = _SHA256[os]
    return f"""\
_install_taplo() (
  local arch checksum installed tmp actual
  case "$(detect_arch)" in
    x86_64) arch=x86_64; checksum={checksums["x86_64"]} ;;
    aarch64|arm64) arch=aarch64; checksum={checksums["aarch64"]} ;;
    *) error "unsupported arch for Taplo: $(detect_arch)"; exit 1 ;;
  esac
  installed="$HOME/bin/taplo"
  if [ -e "$installed" ] || [ -L "$installed" ]; then
    if [ ! -f "$installed" ] || [ -L "$installed" ]; then
      error "unsafe Taplo binary destination: $installed"
      exit 1
    fi
  fi
  if [ -x "$installed" ] && [ "$(sha256_file "$installed")" = "$checksum" ] && bin_version_matches "$installed" "{_VERSION}" --version; then
    exit 0
  fi
  ensure_dir "$HOME/bin"
  tmp="$(mktemp "$HOME/bin/.taplo.XXXXXX")"
  trap 'rm -f -- "$tmp"' EXIT
  curl -fsSL "{_RELEASE_BASE}/taplo-{asset_os}-${{arch}}.gz" | gzip -dc > "$tmp"
  actual="$(sha256_file "$tmp")"
  if [ "$actual" != "$checksum" ]; then
    error "checksum mismatch for Taplo"
    exit 1
  fi
  chmod 0755 "$tmp"
  if ! bin_version_matches "$tmp" "{_VERSION}" --version; then
    error "version mismatch for Taplo"
    exit 1
  fi
  mv -f -- "$tmp" "$installed"
  tmp=""
)
_install_taplo
"""


@dataclass(frozen=True)
class Taplo:
    name: str = "taplo"

    def applies_to(self, env: Environment) -> bool:
        return env.name in {"debian", "macos"}

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_setup(env.os))
