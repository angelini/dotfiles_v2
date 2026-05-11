from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_DEPS_BY_OS: dict[OS, tuple[str, ...]] = {
    OS.MACOS: ("mercurial",),
    OS.DEBIAN: ("curl", "git", "make", "bison", "gcc", "libc6-dev"),
}

_INSTALL_GO = """\
GO_VERSION="1.24.0"
GO_DIR="$HOME/.local/share/go"
if [ ! -d "$GO_DIR" ] || [ ! -x "$GO_DIR/bin/go" ] || [ "$("$GO_DIR/bin/go" version | awk '{print $3}')" != "go$GO_VERSION" ]; then
  log "installing go $GO_VERSION..."
  rm -rf "$GO_DIR"
  ARCH="$(detect_arch)"
  case "$ARCH" in
    x86_64) GO_ARCH="amd64" ;;
    arm64|aarch64) GO_ARCH="arm64" ;;
    *) error "unsupported arch: $ARCH"; return 1 ;;
  esac
  OS_NAME="$(uname -s | tr '[:upper:]' '[:lower:]')"
  download_tar "$GO_DIR" "https://go.dev/dl/go${GO_VERSION}.${OS_NAME}-${GO_ARCH}.tar.gz" 1
fi
"""

_BASHRC = """\
export GOPATH="${GOPATH:-$HOME/go}"
export GOROOT="$HOME/.local/share/go"
export PATH="$GOROOT/bin:$GOPATH/bin:$PATH"
"""


@dataclass(frozen=True)
class GoLang:
    name: str = "go_lang"

    def applies_to(self, env: Environment) -> bool:
        return env.os in _DEPS_BY_OS

    def render(self, env: Environment) -> Fragment:
        deps = " ".join(_DEPS_BY_OS[env.os])
        body = f"install_packages {deps}\n{_INSTALL_GO}"
        return Fragment(setup=body, bashrc=_BASHRC)
