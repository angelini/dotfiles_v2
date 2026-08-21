from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_VERSION = "0.16.0"
_ASSET_OS: dict[OS, str] = {
    OS.DEBIAN: "linux",
    OS.MACOS: "macos",
}
_SHA256: dict[OS, dict[str, str]] = {
    OS.DEBIAN: {
        "x86_64": "70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00",
        "aarch64": "ea4b09bfb22ec6f6c6ceac57ab63efb6b46e17ab08d21f69f3a48b38e1534f17",
    },
    OS.MACOS: {
        "x86_64": "0387557ed1877bc6a2e1802c8391953baddba76081876301c522f52977b52ba7",
        "aarch64": "b23d70deaa879b5c2d486ed3316f7eaa53e84acf6fc9cc747de152450d401489",
    },
}


def _setup(os: OS) -> str:
    asset_os = _ASSET_OS[os]
    checksums = _SHA256[os]
    dependency_setup = "install_package xz-utils\n" if os is OS.DEBIAN else ""
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
        return env.name in {"debian", "macos"}

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_setup(env.os), bashrc=_BASHRC)
