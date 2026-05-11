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
    "load_secrets",
    "install_config_template",
    "install_script",
    "download_script",
    "download_tar",
    "log",
    "error",
    "ask",
    "component_begin",
    "component_end",
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

load_secrets() {
  [ "${_DOTGEN_SECRETS_LOADED:-0}" = 1 ] && return 0
  local f="${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/secrets.env"
  if [ ! -r "$f" ]; then
    error "missing secrets file: $f"
    error "copy from \$DIR/config/dotgen/secrets.env.template and fill in"
    return 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "$f"
  set +a
  _DOTGEN_SECRETS_LOADED=1
}

install_config_template() {
  local src="$1" dst="$2" vars="$3"
  load_secrets || return 1
  local missing=() v subst_spec=""
  for v in $vars; do
    if [ -z "${!v:-}" ]; then
      missing+=("$v")
    fi
    subst_spec="${subst_spec}\${${v}} "
  done
  if [ ${#missing[@]} -gt 0 ]; then
    error "secrets.env missing values: ${missing[*]}"
    return 1
  fi
  if ! bin_exists envsubst; then
    error "envsubst not installed (gettext)"
    return 1
  fi
  local rendered
  rendered="$(mktemp)"
  envsubst "$subst_spec" < "$src" > "$rendered"
  if [ "$DOTGEN_MODE" = diff ]; then
    if [ ! -e "$dst" ]; then
      printf '+ NEW    %s (templated)\n' "$dst"
    elif ! cmp -s "$rendered" "$dst"; then
      printf '~ CHANGE %s (templated)\n' "$dst"
      diff -u "$dst" "$rendered" || true
    fi
    rm -f "$rendered"
    return 0
  fi
  ensure_dir "$(dirname "$dst")"
  install -m 0644 "$rendered" "$dst"
  rm -f "$rendered"
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

download_script() {
  local name="$1" url="$2"
  if [ "$DOTGEN_MODE" = diff ]; then
    [ -x "$HOME/bin/$name" ] || printf '+ INSTALL script %s (%s)\n' "$name" "$url"
    return 0
  fi
  ensure_dir "$HOME/bin"
  curl -fsSL "$url" -o "$HOME/bin/$name"
  chmod +x "$HOME/bin/$name"
}

download_tar() {
  local dir="$1" url="$2" strip="${3:-1}"
  if [ "$DOTGEN_MODE" = diff ]; then
    [ -d "$dir" ] || printf '+ INSTALL tar %s (%s)\n' "$dir" "$url"
    return 0
  fi
  ensure_dir "$dir"
  curl -fsSL "$url" | tar -xz -C "$dir" --strip-components="$strip"
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
  local name="$1"
  if [ "$DOTGEN_MODE" = diff ]; then
    printf -- '--- %s ---\n' "$name"
    return 0
  fi

  # Save original stdout/stderr if not already saved
  if [ -z "${_ORIG_STDOUT:-}" ]; then
    exec 3>&1 4>&2
    _ORIG_STDOUT=3
    _ORIG_STDERR=4
  fi

  printf '  %-30s ' "$name..." >&3
  _COMP_LOG=$(mktemp)
  exec >"$_COMP_LOG" 2>&1
}

component_end() {
  local name="$1" rc="$2"
  if [ "$DOTGEN_MODE" = diff ]; then
    return 0
  fi

  # Restore original stdout/stderr
  exec 1>&3 2>&4

  if [ "$rc" -eq 0 ]; then
    printf '\033[1;32mDONE\033[0m\n'
  else
    printf '\033[1;31mFAIL\033[0m (exit %d)\n' "$rc"
    cat "$_COMP_LOG"
  fi
  rm -f "$_COMP_LOG"
  unset _COMP_LOG
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
  if pkg_installed "$1"; then
    return 0
  fi
  if bin_exists sudo; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$1"
  else
    DEBIAN_FRONTEND=noninteractive apt-get install -y "$1"
  fi
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
  local sudo_cmd=""
  bin_exists sudo && sudo_cmd="sudo"
  case "$kind" in
    apt)
      $sudo_cmd install -d -m 0755 /etc/apt/keyrings
      if [ -n "$key" ]; then
        curl -fsSL "$key" | $sudo_cmd gpg --dearmor --yes -o "/etc/apt/keyrings/$id.gpg"
      fi
      if [[ "$src" == http*://* ]]; then
        curl -fsSL "$src" | $sudo_cmd tee "/etc/apt/sources.list.d/$id.list" >/dev/null
      else
        echo "$src" | sed "s|\[signed-by=[^]]*\]|\[signed-by=/etc/apt/keyrings/$id.gpg\]|" | $sudo_cmd tee "/etc/apt/sources.list.d/$id.list" >/dev/null
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
  if bin_exists sudo; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -y
  else
    DEBIAN_FRONTEND=noninteractive apt-get update -y
  fi
}

service_enable() {
  if [ "$DOTGEN_MODE" = diff ]; then
    systemctl is-enabled --quiet "$1" 2>/dev/null || printf '+ ENABLE service %s\n' "$1"
    return 0
  fi
  if bin_exists sudo; then
    sudo systemctl enable --now "$1"
  else
    systemctl enable --now "$1"
  fi
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
    OS.MACOS: _SHIM_MACOS,
}


@dataclass(frozen=True)
class OSShim:
    os: OS

    def render(self) -> str:
        header = f"# os_shim.sh — {self.os.value}\n"
        return header + _SHIMS[self.os].lstrip("\n")
