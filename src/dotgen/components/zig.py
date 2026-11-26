from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_VERSION = "0.17.1"
_ASSET_OS: dict[OS, str] = {
    OS.CACHYOS: "linux",
    OS.DEBIAN: "linux",
    OS.MACOS: "macos",
}
_SHA256_LINUX = {
    "x86_64": "3581863e3cbcfd0fce0efc682ce7e9e93da96668a977791d356a26d2a7e9b17a",
    "aarch64": "a1546d5646eb184437918d6635ca6b762a0e889eac09cef720ee7a1ed3fe7795",
}
_SHA256: dict[OS, dict[str, str]] = {
    OS.CACHYOS: _SHA256_LINUX,
    OS.DEBIAN: _SHA256_LINUX,
    OS.MACOS: {
        "x86_64": "9af07b20319fbd0c92ee46ad23e81d6a782b1aaea2cfb8dcbff35f1d2c7ddbb7",
        "aarch64": "75f1bc7a1e9852f17ec9a0c1895f767c4ec56d46bc8a834920eece1d0359dd8d",
    },
}


def _setup(os: OS) -> str:
    asset_os = _ASSET_OS[os]
    checksums = _SHA256[os]
    dependency_setup = f"install_package {'xz-utils' if os is OS.DEBIAN else 'xz'}\n" if os.is_linux else ""
    installer = f"""\
_install_zig() (
  local arch checksum zig_dir parent stage archive actual
  case "$(detect_arch)" in
    x86_64) arch=x86_64; checksum={checksums["x86_64"]} ;;
    aarch64|arm64) arch=aarch64; checksum={checksums["aarch64"]} ;;
    *) error "unsupported arch for Zig: $(detect_arch)"; exit 1 ;;
  esac
  zig_dir="$HOME/.local/share/zig"
  if [ -e "$zig_dir" ] || [ -L "$zig_dir" ]; then
    if [ ! -d "$zig_dir" ] || [ -L "$zig_dir" ]; then
      error "unsafe Zig installation destination: $zig_dir"
      exit 1
    fi
  fi
  if [ -x "$zig_dir/zig" ] && [ "$("$zig_dir/zig" version)" = "{_VERSION}" ]; then
    exit 0
  fi
  parent="$HOME/.local/share"
  ensure_dir "$parent"
  stage="$(mktemp -d "$parent/.zig.XXXXXX")"
  archive="$(mktemp "$parent/.zig-archive.XXXXXX")"
  trap 'rm -rf -- "$stage"; rm -f -- "$archive"' EXIT
  curl -fsSL "https://ziglang.org/download/{_VERSION}/zig-${{arch}}-{asset_os}-{_VERSION}.tar.xz" -o "$archive"
  actual="$(sha256_file "$archive")"
  if [ "$actual" != "$checksum" ]; then
    error "checksum mismatch for Zig"
    exit 1
  fi
  tar -xJf "$archive" -C "$stage" --strip-components=1
  if [ ! -x "$stage/zig" ] || [ "$("$stage/zig" version)" != "{_VERSION}" ]; then
    error "version mismatch for Zig"
    exit 1
  fi
  rm -rf -- "$zig_dir"
  mv -- "$stage" "$zig_dir"
  stage=""
)
_install_zig
"""
    return dependency_setup + installer


_BASHRC = 'export PATH="$HOME/.local/share/zig:$PATH"\n'


@dataclass(frozen=True)
class Zig:
    name: str = "zig"

    def applies_to(self, env: Environment) -> bool:
        return env.name != "debian-docker" and env.os in _ASSET_OS

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_setup(env.os), bashrc=_BASHRC)
