from dataclasses import dataclass

from dotgen.types import OS

SHIM_FUNCTIONS: tuple[str, ...] = (
    "detect_os",
    "detect_arch",
    "bin_exists",
    "pkg_installed",
    "install_package",
    "install_packages",
    "remove_packages",
    "install_cask",
    "add_repo",
    "update_pkg_index",
    "service_enable",
    "service_mask",
    "bin_version_matches",
    "download_bin",
    "download_tar_bin",
    "link_file",
    "ensure_dir",
    "install_config",
    "install_json_patch",
    "install_config_dir",
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
    "install_npm_global",
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
  ensure_dir "$(dirname "$dst")"
  ln -sf "$src" "$dst"
}

install_config() {
  local src="$1" dst="$2"
  ensure_dir "$(dirname "$dst")"
  install -m 0644 "$src" "$dst"
}

install_json_patch() (
  if [ "$#" -ne 2 ] && [ "$#" -ne 3 ]; then
    error "install_json_patch: expected two or three arguments"
    exit 1
  fi
  local patch="$1" dst="$2" mode="${3:-0600}"
  local patch_tmp="" live_tmp="" candidate="" staging="" status
  local normalized="" parent target part
  local json_object_filter='length == 1 and (.[0] | type == "object") and ([.[0] | .. | numbers | select(isnan or isinfinite)] | length == 0)'
  local -a dst_parts=() components=()
  local i

  case "$mode" in
    0[0-7][0-7][0-7]) ;;
    *)
      error "install_json_patch: invalid mode: $mode"
      exit 1
      ;;
  esac
  if ! bin_exists jq; then
    error "install_json_patch: jq not installed"
    exit 1
  fi
  if [ -L "$patch" ] || [ ! -f "$patch" ]; then
    error "install_json_patch: patch is not a regular non-symlink file: $patch"
    exit 1
  fi
  if [ -e "$dst" ] || [ -L "$dst" ]; then
    if [ -L "$dst" ] || [ ! -f "$dst" ]; then
      error "install_json_patch: destination is not a regular non-symlink file: $dst"
      exit 1
    fi
  fi

  if [[ "$dst" != /* ]]; then
    dst="$PWD/$dst"
  fi
  IFS=/ read -r -a components <<< "$dst"
  for part in "${components[@]}"; do
    case "$part" in
      ''|.) ;;
      ..) [ "${#dst_parts[@]}" -gt 0 ] && unset 'dst_parts[${#dst_parts[@]}-1]' ;;
      *) dst_parts+=("$part") ;;
    esac
  done
  for part in "${dst_parts[@]}"; do
    normalized="$normalized/$part"
  done
  [ -n "$normalized" ] || { error "install_json_patch: destination must name a file"; exit 1; }
  dst="$normalized"
  parent="${dst%/*}"
  [ -n "$parent" ] || parent=/

  target=/
  for ((i=0; i+1<${#dst_parts[@]}; i++)); do
    part="${dst_parts[i]}"
    target="${target%/}/$part"
    if [ -L "$target" ]; then
      error "install_json_patch: symlink destination ancestor: $target"
      exit 1
    fi
    if [ -e "$target" ] && [ ! -d "$target" ]; then
      error "install_json_patch: destination ancestor is not a directory: $target"
      exit 1
    fi
  done

  trap 'status=$?
set +e
trap - EXIT HUP INT TERM
[ -z "$patch_tmp" ] || rm -f -- "$patch_tmp"
[ -z "$live_tmp" ] || rm -f -- "$live_tmp"
[ -z "$candidate" ] || rm -f -- "$candidate"
[ -z "$staging" ] || rm -f -- "$staging"
exit "$status"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  umask 077
  patch_tmp="$(mktemp "${TMPDIR:-/tmp}/dotgen-json-patch-input.XXXXXX")" || exit 1
  live_tmp="$(mktemp "${TMPDIR:-/tmp}/dotgen-json-live-input.XXXXXX")" || exit 1
  candidate="$(mktemp "${TMPDIR:-/tmp}/dotgen-json-candidate.XXXXXX")" || exit 1
  if ! cat -- "$patch" > "$patch_tmp"; then
    error "install_json_patch: cannot read patch: $patch"
    exit 1
  fi
  if ! jq -e -s "$json_object_filter" "$patch_tmp" >/dev/null 2>&1; then
    error "install_json_patch: patch must contain a top-level JSON object: $patch"
    exit 1
  fi
  if [ -f "$dst" ]; then
    if ! cat -- "$dst" > "$live_tmp"; then
      error "install_json_patch: cannot read destination: $dst"
      exit 1
    fi
  else
    printf '{}\n' > "$live_tmp"
  fi
  if ! jq -e -s "$json_object_filter" "$live_tmp" >/dev/null 2>&1; then
    error "install_json_patch: destination must contain a top-level JSON object: $dst"
    exit 1
  fi
  if ! jq -S -s '.[0] * .[1]' "$live_tmp" "$patch_tmp" > "$candidate"; then
    error "install_json_patch: failed to merge JSON: $dst"
    exit 1
  fi

  if [ -f "$dst" ] && cmp -s "$candidate" "$dst" && [ "$(find "$dst" -prune -perm "$mode" -exec printf x \; 2>/dev/null)" = x ]; then
    exit 0
  fi

  ensure_dir "$parent" || exit 1
  target=/
  for ((i=0; i+1<${#dst_parts[@]}; i++)); do
    part="${dst_parts[i]}"
    target="${target%/}/$part"
    if [ -L "$target" ] || [ ! -d "$target" ]; then
      error "install_json_patch: unsafe destination ancestor: $target"
      exit 1
    fi
  done
  staging="$(mktemp "$parent/.dotgen-json-patch.XXXXXX")" || exit 1
  if ! install -m "$mode" "$candidate" "$staging"; then
    exit 1
  fi
  target=/
  for ((i=0; i+1<${#dst_parts[@]}; i++)); do
    part="${dst_parts[i]}"
    target="${target%/}/$part"
    if [ -L "$target" ] || [ ! -d "$target" ]; then
      error "install_json_patch: unsafe destination ancestor: $target"
      exit 1
    fi
  done
  if [ -e "$dst" ] || [ -L "$dst" ]; then
    if [ -L "$dst" ] || [ ! -f "$dst" ]; then
      error "install_json_patch: destination is not a regular non-symlink file: $dst"
      exit 1
    fi
  fi
  mv -f -- "$staging" "$dst" || exit 1
  staging=""
)

install_config_dir() {
  if [ "$#" -eq 2 ]; then
    local src="$1" dst="$2" rel conflict=0
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
        fi
      done < <(cd "$src" && find . -type f -print0)
    fi
    if [ "$conflict" = 1 ]; then
      return 1
    fi
    ensure_dir "$dst"
    cp -Rp "$src"/. "$dst"/
    return
  fi
  if [ "$#" -lt 3 ]; then
    error "install_config_dir: expected two or at least three arguments"
    return 1
  fi
  (
    local src="$1" dst="$2" identity="$3" normalized part rel target state manifest
    local inventory_dirs inventory_files inventory_other publish_tmp record preserve
    local -a dst_parts=() files=() dirs=() old_files=() components=() preserves=("${@:4}")
    local i j seen preserved
    trap 'rm -f -- "${inventory_dirs:-}" "${inventory_files:-}" "${inventory_other:-}" "${publish_tmp:-}"' EXIT

    if [[ ! "$identity" =~ ^[a-z0-9][a-z0-9._-]{0,63}$ ]] || [ "$identity" = . ] || [ "$identity" = .. ]; then
      error "install_config_dir: invalid managed identity: $identity"
      return 1
    fi
    if [[ "$dst" != /* ]]; then
      dst="$PWD/$dst"
    fi
    IFS=/ read -r -a components <<< "$dst"
    for part in "${components[@]}"; do
      case "$part" in ''|.) ;; ..) [ "${#dst_parts[@]}" -gt 0 ] && unset 'dst_parts[${#dst_parts[@]}-1]' ;; *) dst_parts+=("$part") ;; esac
    done
    normalized=
    for part in "${dst_parts[@]}"; do
      normalized="$normalized/$part"
    done
    [ -n "$normalized" ] || normalized=/
    dst="$normalized"
    state="${XDG_STATE_HOME:-$HOME/.local/state}/dotgen/install-config-dir"
    manifest="$state/$identity.manifest"

    if [ ! -d "$src" ] || [ -L "$src" ]; then
      error "install_config_dir: missing source directory: $src"
      return 1
    fi
    inventory_dirs="$(mktemp "${TMPDIR:-/tmp}/dotgen-config-dirs.XXXXXX")" || return 1
    inventory_files="$(mktemp "${TMPDIR:-/tmp}/dotgen-config-files.XXXXXX")" || return 1
    inventory_other="$(mktemp "${TMPDIR:-/tmp}/dotgen-config-other.XXXXXX")" || return 1
    (cd "$src" && find . -mindepth 1 -type d -print0) >"$inventory_dirs" || { error "install_config_dir: source directory walk failed: $src"; return 1; }
    (cd "$src" && find . -type f -print0) >"$inventory_files" || { error "install_config_dir: source file walk failed: $src"; return 1; }
    (cd "$src" && find . -mindepth 1 ! -type f ! -type d -print0) >"$inventory_other" || { error "install_config_dir: source entry walk failed: $src"; return 1; }
    if [ -s "$inventory_other" ]; then
      error "install_config_dir: source contains non-file entry: $src"
      return 1
    fi
    while IFS= read -r -d '' record; do dirs+=("${record#./}"); done <"$inventory_dirs"
    while IFS= read -r -d '' record; do files+=("${record#./}"); done <"$inventory_files"
    for rel in "${dirs[@]}" "${files[@]}"; do
      [ -n "$rel" ] && [[ "$rel" != /* ]] || { error "install_config_dir: invalid source path"; return 1; }
      IFS=/ read -r -a components <<< "$rel"
      for part in "${components[@]}"; do
        case "$part" in ''|.|..) error "install_config_dir: invalid source path: $rel"; return 1 ;; esac
      done
    done
    for ((i=0; i<${#files[@]}; i++)); do
      for ((j=i+1; j<${#files[@]}; j++)); do
        [ "${files[i]}" != "${files[j]}" ] || { error "install_config_dir: duplicate source path: ${files[i]}"; return 1; }
      done
    done
    for preserve in "${preserves[@]}"; do
      [ -n "$preserve" ] && [[ "$preserve" != /* ]] && [[ "$preserve" != */ ]] || { error "install_config_dir: invalid preserved path: $preserve"; return 1; }
      IFS=/ read -r -a components <<< "$preserve"
      for part in "${components[@]}"; do
        case "$part" in ''|.|..) error "install_config_dir: invalid preserved path: $preserve"; return 1 ;; esac
      done
      for rel in "${dirs[@]}" "${files[@]}"; do
        [ "$preserve" != "$rel" ] || { error "install_config_dir: preserved path exists in source inventory: $preserve"; return 1; }
      done
    done
    for ((i=0; i<${#preserves[@]}; i++)); do
      for ((j=i+1; j<${#preserves[@]}; j++)); do
        [ "${preserves[i]}" != "${preserves[j]}" ] || { error "install_config_dir: duplicate preserved path: ${preserves[i]}"; return 1; }
      done
    done

    if [ -e "$manifest" ] || [ -L "$manifest" ]; then
      if [ -L "$manifest" ] || [ ! -f "$manifest" ]; then
        error "install_config_dir: invalid manifest: $manifest"
        return 1
      fi
      exec 9<"$manifest" || { error "install_config_dir: cannot read manifest: $manifest"; return 1; }
      IFS= read -r -d '' record <&9 || { error "install_config_dir: invalid manifest schema: $manifest"; return 1; }
      [ "$record" = dotgen-install-config-dir-v1 ] || { error "install_config_dir: invalid manifest schema: $manifest"; return 1; }
      IFS= read -r -d '' record <&9 || { error "install_config_dir: invalid manifest schema: $manifest"; return 1; }
      [ "$record" = "$dst" ] || { error "install_config_dir: manifest destination mismatch: $manifest"; return 1; }
      while true; do
        record=
        if IFS= read -r -d '' record <&9; then
          old_files+=("$record")
        else
          [ -z "$record" ] || { error "install_config_dir: invalid manifest schema: $manifest"; return 1; }
          break
        fi
      done
      exec 9<&-
      for rel in "${old_files[@]}"; do
        [ -n "$rel" ] && [[ "$rel" != /* ]] || { error "install_config_dir: invalid manifest path"; return 1; }
        IFS=/ read -r -a components <<< "$rel"
        for part in "${components[@]}"; do case "$part" in ''|.|..) error "install_config_dir: invalid manifest path: $rel"; return 1;; esac; done
      done
      for ((i=0; i<${#old_files[@]}; i++)); do
        for ((j=i+1; j<${#old_files[@]}; j++)); do
          [ "${old_files[i]}" != "${old_files[j]}" ] || { error "install_config_dir: duplicate manifest path: ${old_files[i]}"; return 1; }
        done
      done
    fi

    target=/
    for part in "${dst_parts[@]}"; do
      target="$target$part"
      [ -L "$target" ] && { error "install_config_dir: symlink destination ancestor: $target"; return 1; }
      target="$target/"
    done
    [ -L "$dst" ] && { error "install_config_dir: symlink destination: $dst"; return 1; }
    if [ -e "$dst" ] && [ ! -d "$dst" ]; then error "install_config_dir: $dst exists but is not a directory"; return 1; fi
    for rel in "${dirs[@]}"; do
      target="$dst/$rel"
      [ -L "$target" ] && { error "install_config_dir: symlink destination path: $target"; return 1; }
      [ ! -e "$target" ] || [ -d "$target" ] || { error "install_config_dir: $target exists but is not a directory"; return 1; }
    done
    for rel in "${files[@]}"; do
      target="$dst/$rel"
      [ -L "$target" ] && { error "install_config_dir: symlink destination path: $target"; return 1; }
      [ ! -e "$target" ] || [ -f "$target" ] || { error "install_config_dir: $target exists but is not a regular file"; return 1; }
    done
    for rel in "${old_files[@]}"; do
      preserved=0; for preserve in "${preserves[@]}"; do [ "$rel" != "$preserve" ] || preserved=1; done
      [ "$preserved" = 0 ] || continue
      seen=0; for record in "${files[@]}"; do [ "$rel" != "$record" ] || seen=1; done
      [ "$seen" = 0 ] || continue
      target="$dst/$rel"
      [ ! -e "$target" ] && [ ! -L "$target" ] && continue
      [ -f "$target" ] && [ ! -L "$target" ] || { error "install_config_dir: retired managed path is not a regular file: $target"; return 1; }
    done
    for rel in "${old_files[@]}"; do
      preserved=0; for preserve in "${preserves[@]}"; do [ "$rel" != "$preserve" ] || preserved=1; done
      [ "$preserved" = 0 ] || continue
      seen=0; for record in "${files[@]}"; do [ "$rel" != "$record" ] || seen=1; done
      [ "$seen" = 0 ] && [ -f "$dst/$rel" ] && rm -f -- "$dst/$rel"
    done
    ensure_dir "$dst" || return 1
    cp -Rp "$src"/. "$dst"/ || return 1
    ensure_dir "$state" || return 1
    publish_tmp="$(mktemp "$state/$identity.manifest.XXXXXX")" || return 1
    printf '%s\0' dotgen-install-config-dir-v1 "$dst" "${files[@]}" >"$publish_tmp" || return 1
    mv -f -- "$publish_tmp" "$manifest" || return 1
    publish_tmp=""
  )
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
  tmp="$(mktemp)"
  curl -fsSL "$url" -o "$tmp"
  chmod +x "$tmp"
  "$tmp" "$@"
  rm -f "$tmp"
}

bin_version_matches() {
  local bin="$1" expected="$2" output
  shift 2
  [ -x "$bin" ] || return 1
  [ -n "$expected" ] || return 1
  output="$("$bin" "$@" 2>&1)" || return 1
  awk -v expected="$expected" '{ for (i = 1; i <= NF; i++) if ($i == expected) found = 1 } END { exit(found ? 0 : 1) }' <<< "$output"
}

download_bin() {
  local name="$1" url="$2" expected="${3:-}"
  if [ "$#" -gt 2 ]; then shift 3; else shift 2; fi
  if [ -n "$expected" ]; then
    bin_version_matches "$HOME/bin/$name" "$expected" "$@" && return 0
  fi
  ensure_dir "$HOME/bin"
  curl -fsSL "$url" -o "$HOME/bin/$name"
  chmod +x "$HOME/bin/$name"
}

download_tar_bin() {
  local name="$1" url="$2" inner="${3:-$1}" expected="${4:-}"
  if [ "$#" -gt 3 ]; then shift 4; else shift "$#"; fi
  if [ -n "$expected" ]; then
    bin_version_matches "$HOME/bin/$name" "$expected" "$@" && return 0
  fi
  ensure_dir "$HOME/bin"
  curl -fsSL "$url" | tar -xzO "$inner" > "$HOME/bin/$name"
  chmod +x "$HOME/bin/$name"
}

download_script() {
  local name="$1" url="$2"
  ensure_dir "$HOME/bin"
  curl -fsSL "$url" -o "$HOME/bin/$name"
  chmod +x "$HOME/bin/$name"
}

download_tar() {
  local dir="$1" url="$2" strip="${3:-1}"
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
  local fnm_bin
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
  npm install -g "$@"
}

component_begin() {
  local name="$1"

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
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -y
}

service_enable() {
  sudo systemctl enable --now "$1"
}

service_mask() {
  if [ "$#" -eq 0 ]; then
    error "service_mask: require at least one unit"
    return 1
  fi
  local unit state
  sudo systemctl mask --now "$@" || return 1
  for unit in "$@"; do
    state="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
    if [ "$state" != masked ] || systemctl is-active --quiet "$unit"; then
      error "service_mask: failed to mask and stop $unit"
      return 1
    fi
  done
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
  if brew list --cask --versions "$1" >/dev/null 2>&1; then
    return 0
  fi
  brew install --cask "$1"
}

add_repo() {
  local kind="${1:-}" id="${2:-}" url="${3:-}"
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
  brew update
}

service_enable() {
  return 0
}

service_mask() {
  error "service_mask: debian only"
  return 1
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
