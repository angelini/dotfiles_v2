# os_shim.sh — debian
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
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$1"
}

install_packages() {
  local p
  for p in "$@"; do
    install_package "$p"
  done
}

remove_packages() {
  if [ "$#" -eq 0 ]; then
    error "remove_packages: require at least one package"
    return 1
  fi
  local p installed=()
  for p in "$@"; do
    if pkg_installed "$p"; then
      installed+=("$p")
    fi
  done
  if [ "$DOTGEN_MODE" = diff ]; then
    for p in "${installed[@]}"; do
      printf '%s\n' "- REMOVE pkg $p"
    done
    return 0
  fi
  [ "${#installed[@]}" -eq 0 ] && return 0
  sudo DEBIAN_FRONTEND=noninteractive apt-get remove -y "${installed[@]}"
}

install_cask() {
  error "install_cask: macOS only"
  return 1
}

add_repo() {
  local kind="${1:-}"
  case "$kind" in
    apt)
      local id="${2:-}" src="${3:-}" key="${4:-}"
      if [ "$DOTGEN_MODE" = diff ]; then
        [ -f "/etc/apt/sources.list.d/$id.list" ] || printf '+ ADD REPO %s (%s)\n' "$id" "$kind"
        return 0
      fi
      sudo install -d -m 0755 /etc/apt/keyrings
      if [ -n "$key" ]; then
        curl -fsSL "$key" | sudo gpg --dearmor --yes -o "/etc/apt/keyrings/$id.gpg"
      fi
      if [[ "$src" == http*://* ]]; then
        curl -fsSL "$src" | sudo tee "/etc/apt/sources.list.d/$id.list" >/dev/null
      else
        echo "$src" | sed "s|\[signed-by=[^]]*\]|\[signed-by=/etc/apt/keyrings/$id.gpg\]|" | sudo tee "/etc/apt/sources.list.d/$id.list" >/dev/null
      fi
      ;;
    apt-deb822)
      (
        if [ "$#" -ne 4 ]; then
          error "add_repo apt-deb822: require id, source content, and armored key URL"
          return 1
        fi
        local id="$2" source="$3" key_url="$4" key_target source_target legacy_key legacy_source
        local key_tmp source_tmp gpg_home key_stage="" source_stage="" validation status
        if ! [[ "$id" =~ ^[a-z0-9][a-z0-9._-]*$ ]]; then
          error "add_repo apt-deb822: invalid repository id '$id'"
          return 1
        fi
        key_target="/etc/apt/keyrings/$id.asc"
        source_target="/etc/apt/sources.list.d/$id.sources"
        legacy_key="/etc/apt/keyrings/$id.gpg"
        legacy_source="/etc/apt/sources.list.d/$id.list"
        while [[ "$source" == *$'\n' ]]; do source="${source%$'\n'}"; done
        if [ -z "$source" ] || [[ "$source" == *$'\r'* ]]; then
          error "add_repo apt-deb822: invalid source content; remediate the repository stanza"
          return 1
        fi
        validation="$(printf '%s\n' "$source" | awk -v signed_by="$key_target" '
          /^[[:space:]]*$/ { fail="blank line"; exit 1 }
          /^[[:space:]]/ { fail="continuation line"; exit 1 }
          !/^[A-Za-z][A-Za-z0-9-]*: [^[:space:]].*$/ { fail="malformed field line"; exit 1 }
          {
            split($0, pair, ": "); field=pair[1]; value=substr($0, length(field) + 3)
            if (seen[field]++) { fail="duplicate field " field; exit 1 }
            values[field]=value
          }
          END {
            if (fail) { print fail > "/dev/stderr"; exit 1 }
            split("Types URIs Suites Components Architectures Signed-By", required, " ")
            for (i in required) if (!(required[i] in values)) { print "missing " required[i] > "/dev/stderr"; exit 1 }
            if (values["Signed-By"] != signed_by) { print "Signed-By must be " signed_by > "/dev/stderr"; exit 1 }
          }
        ' 2>&1)" || { error "add_repo apt-deb822: $validation; remediate the repository stanza"; return 1; }
        for target in "$key_target" "$source_target"; do
          if [ -e "$target" ] || [ -L "$target" ]; then
            if [ -L "$target" ] || [ ! -f "$target" ]; then
              error "add_repo apt-deb822: unsafe target $target; remediate it manually"
              return 1
            fi
          fi
        done
        for target in "$legacy_key" "$legacy_source"; do
          if [ -e "$target" ] || [ -L "$target" ]; then
            error "add_repo apt-deb822: legacy collision at $target; remediate it manually"
            return 1
          fi
        done
        key_tmp=""; source_tmp=""; gpg_home=""
        trap 'status=$?
set +e
[ -z "$key_tmp" ] || rm -rf "$key_tmp"
[ -z "$source_tmp" ] || rm -rf "$source_tmp"
[ -z "$gpg_home" ] || rm -rf "$gpg_home"
[ -z "$key_stage" ] || sudo rm -f "$key_stage"
[ -z "$source_stage" ] || sudo rm -f "$source_stage"
exit "$status"' EXIT
        key_tmp="$(mktemp)" || return 1
        source_tmp="$(mktemp)" || return 1
        gpg_home="$(mktemp -d)" || return 1
        chmod 0700 "$gpg_home" || return 1
        printf '%s\n' "$source" > "$source_tmp"
        if ! curl -fsSL "$key_url" -o "$key_tmp"; then
          error "add_repo apt-deb822: failed to download key; remediate the key URL"
          return 1
        fi
        if ! grep -q -- '-----BEGIN PGP PUBLIC KEY BLOCK-----' "$key_tmp" || ! GNUPGHOME="$gpg_home" gpg --batch --show-keys "$key_tmp" >/dev/null; then
          error "add_repo apt-deb822: invalid armored key; remediate the key URL"
          return 1
        fi
        local key_changed=1 source_changed=1
        [ -f "$key_target" ] && cmp -s "$key_tmp" "$key_target" && key_changed=0
        [ -f "$source_target" ] && cmp -s "$source_tmp" "$source_target" && source_changed=0
        if [ "$DOTGEN_MODE" = diff ]; then
          if [ "$key_changed" -eq 1 ]; then
            [ -f "$key_target" ] && printf '~ CHANGE REPO KEY %s\n' "$key_target" || printf '+ ADD REPO KEY %s\n' "$key_target"
          fi
          if [ "$source_changed" -eq 1 ]; then
            [ -f "$source_target" ] && printf '~ CHANGE REPO SOURCE %s\n' "$source_target" || printf '+ ADD REPO SOURCE %s\n' "$source_target"
          fi
          return 0
        fi
        [ "$key_changed" -eq 0 ] && [ "$source_changed" -eq 0 ] && return 0
        sudo install -d -m 0755 /etc/apt/keyrings /etc/apt/sources.list.d || return 1
        if [ "$key_changed" -eq 1 ]; then
          key_stage="$(sudo mktemp "/etc/apt/keyrings/.${id}.asc.XXXXXX")" || return 1
          sudo install -m 0644 "$key_tmp" "$key_stage" && sudo mv -f "$key_stage" "$key_target" || return 1
          key_stage=""
        fi
        if [ "$source_changed" -eq 1 ]; then
          source_stage="$(sudo mktemp "/etc/apt/sources.list.d/.${id}.sources.XXXXXX")" || return 1
          sudo install -m 0644 "$source_tmp" "$source_stage" && sudo mv -f "$source_stage" "$source_target" || return 1
          source_stage=""
        fi
      )
      ;;
    *)
      error "add_repo: unsupported kind '$kind' on debian"
      return 1
      ;;
  esac
}

update_pkg_index() {
  [ "$DOTGEN_MODE" = diff ] && return 0
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -y
}

service_enable() {
  if [ "$DOTGEN_MODE" = diff ]; then
    systemctl is-enabled --quiet "$1" 2>/dev/null || printf '+ ENABLE service %s\n' "$1"
    return 0
  fi
  sudo systemctl enable --now "$1"
}

service_mask() {
  if [ "$#" -eq 0 ]; then
    error "service_mask: require at least one unit"
    return 1
  fi
  local unit state
  if [ "$DOTGEN_MODE" = diff ]; then
    for unit in "$@"; do
      state="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
      [ "$state" = masked ] || printf '~ MASK service %s\n' "$unit"
    done
    return 0
  fi
  sudo systemctl mask --now "$@" || return 1
  for unit in "$@"; do
    state="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
    if [ "$state" != masked ] || systemctl is-active --quiet "$unit"; then
      error "service_mask: failed to mask and stop $unit"
      return 1
    fi
  done
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
