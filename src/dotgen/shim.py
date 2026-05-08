from dataclasses import dataclass

from dotgen.types import OS

SHIM_FUNCTIONS: tuple[str, ...] = (
    "detect_os",
    "detect_arch",
    "bin_exists",
    "pkg_installed",
    "install_package",
    "install_packages",
    "install_cask",
    "add_repo",
    "update_pkg_index",
    "service_enable",
    "download_bin",
    "download_tar_bin",
    "link_file",
    "ensure_dir",
    "install_config",
    "install_script",
    "log",
    "error",
    "ask",
)

_SHARED = r"""
detect_arch() {
  uname -m
}

bin_exists() {
  command -v "$1" >/dev/null 2>&1
}

ensure_dir() {
  mkdir -p "$1"
}

link_file() {
  local src="$1" dst="$2"
  if [ "$DOTGEN_MODE" = diff ]; then
    if [ ! -L "$dst" ]; then
      printf '+ LINK   %s -> %s\n' "$dst" "$src"
    elif [ "$(readlink "$dst")" != "$src" ]; then
      printf '~ RELINK %s -> %s (was %s)\n' "$dst" "$src" "$(readlink "$dst")"
    fi
    return 0
  fi
  ensure_dir "$(dirname "$dst")"
  ln -sf "$src" "$dst"
}

install_config() {
  local src="$1" dst="$2"
  if [ "$DOTGEN_MODE" = diff ]; then
    if [ ! -e "$dst" ]; then
      printf '+ NEW    %s\n' "$dst"
    elif ! cmp -s "$src" "$dst"; then
      printf '~ CHANGE %s\n' "$dst"
      diff -u "$dst" "$src" || true
    fi
    return 0
  fi
  ensure_dir "$(dirname "$dst")"
  install -m 0644 "$src" "$dst"
}

install_script() {
  local name="$1" url="$2"
  shift 2
  if bin_exists "$name"; then
    return 0
  fi
  if [ "$DOTGEN_MODE" = diff ]; then
    printf '+ INSTALL script %s (%s)\n' "$name" "$url"
    return 0
  fi
  curl -fsSL "$url" | bash -s -- "$@"
}

download_bin() {
  local name="$1" url="$2"
  if [ "$DOTGEN_MODE" = diff ]; then
    [ -x "$HOME/bin/$name" ] || printf '+ INSTALL bin %s (%s)\n' "$name" "$url"
    return 0
  fi
  ensure_dir "$HOME/bin"
  curl -fsSL "$url" -o "$HOME/bin/$name"
  chmod +x "$HOME/bin/$name"
}

download_tar_bin() {
  local name="$1" url="$2" inner="${3:-$1}"
  if [ "$DOTGEN_MODE" = diff ]; then
    [ -x "$HOME/bin/$name" ] || printf '+ INSTALL bin %s (%s)\n' "$name" "$url"
    return 0
  fi
  ensure_dir "$HOME/bin"
  curl -fsSL "$url" | tar -xzO "$inner" > "$HOME/bin/$name"
  chmod +x "$HOME/bin/$name"
}

log() {
  printf '\033[1;34m[INFO]\033[0m %s\n' "$*" >&2
}

error() {
  printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2
}

ask() {
  local prompt="$1" reply
  printf '%s ' "$prompt" >&2
  read -r reply
  printf '%s' "$reply"
}
"""

_SHIM_DEBIAN = (
    r"""
detect_os() {
  echo debian
}

pkg_installed() {
  dpkg -s "$1" >/dev/null 2>&1
}

install_package() {
  if [ "$DOTGEN_MODE" = diff ]; then
    pkg_installed "$1" || printf '+ INSTALL pkg %s\n' "$1"
    return 0
  fi
  pkg_installed "$1" || sudo apt-get install -y "$1"
}

install_packages() {
  local p
  for p in "$@"; do
    install_package "$p"
  done
}

install_cask() {
  error "install_cask: macOS only"
  return 1
}

add_repo() {
  local kind="$1" id="$2" src="$3" key="${4:-}"
  if [ "$DOTGEN_MODE" = diff ]; then
    [ -f "/etc/apt/sources.list.d/$id.list" ] || printf '+ ADD REPO %s (%s)\n' "$id" "$kind"
    return 0
  fi
  case "$kind" in
    apt)
      sudo install -d -m 0755 /etc/apt/keyrings
      if [ -n "$key" ]; then
        curl -fsSL "$key" | sudo gpg --dearmor --yes -o "/etc/apt/keyrings/$id.gpg"
      fi
      if [[ "$src" == http*://* ]]; then
        curl -fsSL "$src" | sudo tee "/etc/apt/sources.list.d/$id.list" >/dev/null
      else
        echo "$src" | sudo tee "/etc/apt/sources.list.d/$id.list" >/dev/null
      fi
      ;;
    *)
      error "add_repo: unsupported kind '$kind' on debian"
      return 1
      ;;
  esac
}

update_pkg_index() {
  [ "$DOTGEN_MODE" = diff ] && return 0
  sudo apt-get update -y
}

service_enable() {
  if [ "$DOTGEN_MODE" = diff ]; then
    systemctl is-enabled --quiet "$1" 2>/dev/null || printf '+ ENABLE service %s\n' "$1"
    return 0
  fi
  sudo systemctl enable --now "$1"
}
"""
    + _SHARED
)

_SHIM_FEDORA = (
    r"""
detect_os() {
  echo fedora
}

pkg_installed() {
  rpm -q "$1" >/dev/null 2>&1
}

install_package() {
  if [ "$DOTGEN_MODE" = diff ]; then
    pkg_installed "$1" || printf '+ INSTALL pkg %s\n' "$1"
    return 0
  fi
  pkg_installed "$1" || sudo dnf install -y "$1"
}

install_packages() {
  local p
  for p in "$@"; do
    install_package "$p"
  done
}

install_cask() {
  error "install_cask: macOS only"
  return 1
}

add_repo() {
  local kind="$1" id="$2" src="${3:-}"
  if [ "$DOTGEN_MODE" = diff ]; then
    case "$kind" in
      dnf)  [ -f "/etc/yum.repos.d/$id.repo" ] || printf '+ ADD REPO %s (%s)\n' "$id" "$kind" ;;
      copr) printf '+ ADD REPO %s (copr)\n' "$id" ;;
      *)    printf '+ ADD REPO %s (%s)\n' "$id" "$kind" ;;
    esac
    return 0
  fi
  case "$kind" in
    dnf)
      if [[ "$src" == http*://* ]]; then
        sudo curl -fsSL "$src" -o "/etc/yum.repos.d/$id.repo"
      else
        echo "$src" | sudo tee "/etc/yum.repos.d/$id.repo" >/dev/null
      fi
      ;;
    copr)
      sudo dnf -y copr enable "$id"
      ;;
    *)
      error "add_repo: unsupported kind '$kind' on fedora"
      return 1
      ;;
  esac
}

update_pkg_index() {
  [ "$DOTGEN_MODE" = diff ] && return 0
  sudo dnf -y check-update || true
}

service_enable() {
  if [ "$DOTGEN_MODE" = diff ]; then
    systemctl is-enabled --quiet "$1" 2>/dev/null || printf '+ ENABLE service %s\n' "$1"
    return 0
  fi
  sudo systemctl enable --now "$1"
}
"""
    + _SHARED
)

_SHIM_MACOS = (
    r"""
detect_os() {
  echo macos
}

pkg_installed() {
  brew list --versions "$1" >/dev/null 2>&1
}

install_package() {
  if [ "$DOTGEN_MODE" = diff ]; then
    pkg_installed "$1" || printf '+ INSTALL pkg %s\n' "$1"
    return 0
  fi
  pkg_installed "$1" || brew install "$1"
}

install_packages() {
  local p
  for p in "$@"; do
    install_package "$p"
  done
}

install_cask() {
  if [ "$DOTGEN_MODE" = diff ]; then
    brew list --cask --versions "$1" >/dev/null 2>&1 || printf '+ INSTALL cask %s\n' "$1"
    return 0
  fi
  if brew list --cask --versions "$1" >/dev/null 2>&1; then
    return 0
  fi
  brew install --cask "$1"
}

add_repo() {
  local kind="$1" id="$2" url="${3:-}"
  if [ "$DOTGEN_MODE" = diff ]; then
    case "$kind" in
      tap) brew tap | grep -qx "$id" || printf '+ ADD REPO %s (tap)\n' "$id" ;;
      *)   printf '+ ADD REPO %s (%s)\n' "$id" "$kind" ;;
    esac
    return 0
  fi
  case "$kind" in
    tap)
      if [ -n "$url" ]; then
        brew tap "$id" "$url"
      else
        brew tap "$id"
      fi
      ;;
    *)
      error "add_repo: unsupported kind '$kind' on macos"
      return 1
      ;;
  esac
}

update_pkg_index() {
  [ "$DOTGEN_MODE" = diff ] && return 0
  brew update
}

service_enable() {
  return 0
}
"""
    + _SHARED
)

_SHIMS: dict[OS, str] = {
    OS.DEBIAN: _SHIM_DEBIAN,
    OS.FEDORA: _SHIM_FEDORA,
    OS.MACOS: _SHIM_MACOS,
}


@dataclass(frozen=True)
class OSShim:
    os: OS

    def render(self) -> str:
        header = f"# os_shim.sh — {self.os.value}\n"
        return header + _SHIMS[self.os].lstrip("\n")
