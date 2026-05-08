# os_shim.sh — fedora
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
  local name="$1" url="$2" tmp
  shift 2
  if bin_exists "$name"; then
    return 0
  fi
  if [ "$DOTGEN_MODE" = diff ]; then
    printf '+ INSTALL script %s (%s)\n' "$name" "$url"
    return 0
  fi
  tmp="$(mktemp)"
  curl -fsSL "$url" -o "$tmp"
  chmod +x "$tmp"
  "$tmp" "$@"
  rm -f "$tmp"
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

component_begin() {
  [ "$DOTGEN_MODE" = diff ] && printf -- '--- %s ---\n' "$1"
  return 0
}
