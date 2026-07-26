# os_shim.sh — macos
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

remove_packages() {
  error "remove_packages: debian only"
  return 1
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
  local kind="${1:-}" id="${2:-}" url="${3:-}"
  case "$kind" in
    tap)
      if [ "$DOTGEN_MODE" = diff ]; then
        brew tap | grep -qx "$id" || printf '+ ADD REPO %s (tap)\n' "$id"
        return 0
      fi
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

service_mask() {
  error "service_mask: debian only"
  return 1
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

install_config_dir() {
  local src="$1" dst="$2" rel drift=0 conflict=0
  if [ ! -d "$src" ]; then
    error "install_config_dir: missing source directory: $src"
    return 1
  fi
  if [ -e "$dst" ] && [ ! -d "$dst" ]; then
    error "install_config_dir: $dst exists but is not a directory"
    conflict=1
  elif [ -d "$dst" ]; then
    while IFS= read -r -d '' rel; do
      rel="${rel#./}"
      if [ -e "$dst/$rel" ] && [ ! -d "$dst/$rel" ]; then
        error "install_config_dir: $dst/$rel exists but is not a directory"
        conflict=1
      fi
    done < <(cd "$src" && find . -mindepth 1 -type d -print0)
    while IFS= read -r -d '' rel; do
      rel="${rel#./}"
      if [ -e "$dst/$rel" ] && [ ! -f "$dst/$rel" ]; then
        error "install_config_dir: $dst/$rel exists but is not a regular file"
        conflict=1
      elif [ ! -f "$dst/$rel" ] || ! cmp -s "$src/$rel" "$dst/$rel"; then
        drift=1
      fi
    done < <(cd "$src" && find . -type f -print0)
  fi
  if [ "$DOTGEN_MODE" = diff ]; then
    if [ ! -d "$dst" ]; then
      printf '+ COPY   %s\n' "$dst"
    elif [ "$conflict" = 1 ] || [ "$drift" = 1 ]; then
      printf '~ SYNC   %s\n' "$dst"
    fi
    return 0
  fi
  if [ "$conflict" = 1 ]; then
    return 1
  fi
  ensure_dir "$dst"
  cp -Rp "$src"/. "$dst"/
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

install_config_template() (
  local src="$1" dst="$2" vars="$3" mode="${4:-0644}"
  local missing=() v subst_spec="" rendered="" staging="" status
  case "$mode" in
    0[0-7][0-7][0-7]) ;;
    *)
      error "install_config_template: invalid mode: $mode"
      exit 1
      ;;
  esac
  if [ -e "$dst" ] && [ ! -f "$dst" ]; then
    error "install_config_template: destination is not a regular file: $dst"
    exit 1
  fi
  trap 'status=$?; trap - EXIT HUP INT TERM; [ -z "$rendered" ] || rm -f "$rendered"; [ -z "$staging" ] || rm -f "$staging"; exit "$status"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  load_secrets || exit 1
  for v in $vars; do
    if [ -z "${!v:-}" ]; then
      missing+=("$v")
    fi
    subst_spec="${subst_spec}\${${v}} "
  done
  if [ ${#missing[@]} -gt 0 ]; then
    error "secrets.env missing values: ${missing[*]}"
    exit 1
  fi
  if ! bin_exists envsubst; then
    error "envsubst not installed (gettext)"
    exit 1
  fi
  umask 077
  rendered="$(mktemp "${TMPDIR:-/tmp}/dotgen-template.XXXXXX")"
  chmod 0600 "$rendered"
  if ! envsubst "$subst_spec" < "$src" > "$rendered"; then
    exit 1
  fi
  if [ "$DOTGEN_MODE" = diff ]; then
    if [ ! -e "$dst" ]; then
      printf '+ NEW    %s (templated)\n' "$dst"
    elif ! cmp -s "$rendered" "$dst" || [ "$(find "$dst" -prune -perm "$mode" -exec printf x \; 2>/dev/null)" != x ]; then
      printf '~ CHANGE %s (templated)\n' "$dst"
    fi
    exit 0
  fi
  ensure_dir "$(dirname "$dst")"
  staging="$(mktemp "$(dirname "$dst")/.dotgen-template.XXXXXX")"
  if ! install -m "$mode" "$rendered" "$staging"; then
    exit 1
  fi
  if [ -e "$dst" ] && [ ! -f "$dst" ]; then
    error "install_config_template: destination is not a regular file: $dst"
    exit 1
  fi
  mv -f "$staging" "$dst"
)

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

install_npm_global() {
  local pkg="$1" fnm_bin
  if [ "$DOTGEN_MODE" = diff ]; then
    printf '+ INSTALL npm %s\n' "$pkg"
    return 0
  fi
  if ! bin_exists npm; then
    fnm_bin="$HOME/.local/share/fnm/fnm"
    if [ -x "$fnm_bin" ]; then
      eval "$("$fnm_bin" env --shell bash)"
    fi
  fi
  if ! bin_exists npm; then
    error "npm unavailable; node_fnm must run before npm installs"
    return 1
  fi
  npm install -g "$pkg"
}

component_begin() {
  local name="$1"
  if [ "$DOTGEN_MODE" = diff ]; then
    printf -- '--- %s ---\n' "$name"
    return 0
  fi

  # Save original stdio
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

  # Restore stdio
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
