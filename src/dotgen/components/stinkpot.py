from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment, GeneratedBinary
from dotgen.types import OS

_SOURCE_URL = "https://tangled.org/oppi.li/stinkpot/archive/cdf87ffcd36e96f3d49316d57fa17cc6ea8371df?format=tar.gz"
_SOURCE_SHA256 = "3482ea0c2e729de6e24067d97e91eb969cde2c3a3d9610ca2f0f745b2b20ef32"
_GO_VERSION = "1.26.4"

_TARGETS: dict[OS, tuple[tuple[str, str], ...]] = {
    OS.DEBIAN: (("linux", "amd64"), ("linux", "arm64")),
    OS.MACOS: (("darwin", "arm64"),),
}

_SETUP = r"""stinkpot_install() {
  local target rel root src manifest expected actual installed
  local data_dir state_dir marker legacy db install_tmp marker_tmp
  target="$(detect_os):$(detect_arch)"
  case "$target" in
    debian:x86_64) rel="linux-amd64/stinkpot" ;;
    debian:aarch64|debian:arm64) rel="linux-arm64/stinkpot" ;;
    macos:arm64|macos:aarch64) rel="darwin-arm64/stinkpot" ;;
    macos:x86_64)
      error "stinkpot does not support Darwin amd64"
      return 1
      ;;
    *)
      error "stinkpot does not support target $target"
      return 1
      ;;
  esac

  root="$DIR/artifacts/stinkpot"
  src="$root/$rel"
  manifest="$root/SHA256SUMS"
  installed="$HOME/bin/stinkpot"
  if [ ! -f "$src" ] || [ -L "$src" ] || [ ! -x "$src" ]; then
    error "invalid bundled stinkpot executable: $src"
    return 1
  fi
  if [ ! -f "$manifest" ] || [ -L "$manifest" ]; then
    error "invalid stinkpot checksum manifest: $manifest"
    return 1
  fi
  if ! expected="$(awk -v wanted="$rel" '
    NF != 2 || length($1) != 64 || $1 !~ /^[0-9a-f]+$/ || $2 !~ /^[A-Za-z0-9._\/-]+$/ { bad = 1 }
    $2 ~ /^\// || $2 ~ /(^|\/)\.\.(\/|$)/ { bad = 1 }
    { seen[$2]++; if ($2 == wanted) checksum = $1 }
    END {
      for (path in seen) if (seen[path] != 1) bad = 1
      if (bad || seen[wanted] != 1) exit 1
      print checksum
    }
  ' "$manifest")"; then
    error "malformed stinkpot checksum manifest: $manifest"
    return 1
  fi
  case "${target%%:*}" in
    debian)
      if ! actual="$(sha256sum "$src" | awk '{print $1}')"; then
        error "unable to checksum bundled stinkpot executable: $src"
        return 1
      fi
      ;;
    macos)
      if ! actual="$(shasum -a 256 "$src" | awk '{print $1}')"; then
        error "unable to checksum bundled stinkpot executable: $src"
        return 1
      fi
      ;;
  esac
  if [ "$actual" != "$expected" ]; then
    error "stinkpot checksum mismatch: $src"
    return 1
  fi

  data_dir="${XDG_DATA_HOME:-$HOME/.local/share}/stinkpot"
  state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/dotgen/stinkpot"
  marker="$state_dir/bash-history-import-v1"
  legacy="$HOME/.bash_history"
  db="$data_dir/history.db"

  if [ -L "$marker" ] || { [ -e "$marker" ] && [ ! -f "$marker" ]; }; then
    error "invalid stinkpot migration marker: $marker"
    return 1
  fi
  if [ ! -e "$marker" ]; then
    if [ -L "$data_dir" ] || { [ -e "$data_dir" ] && [ ! -d "$data_dir" ]; }; then
      error "invalid stinkpot data directory: $data_dir"
      return 1
    fi
    if [ -L "$db" ] || { [ -e "$db" ] && [ ! -f "$db" ]; }; then
      error "invalid stinkpot database: $db"
      return 1
    fi
    if [ -L "$legacy" ] || { [ -e "$legacy" ] && [ ! -f "$legacy" ]; }; then
      error "invalid legacy Bash history file: $legacy"
      return 1
    fi
  fi

  if [ "$DOTGEN_MODE" = diff ]; then
    if [ ! -f "$installed" ] || [ -L "$installed" ] || [ ! -x "$installed" ]; then
      printf '+ INSTALL %s\n' "$installed"
    elif ! cmp -s "$src" "$installed"; then
      printf '~ CHANGE %s\n' "$installed"
    fi
    if [ ! -e "$marker" ]; then
      printf '+ MIGRATE %s\n' "$legacy"
    fi
    return 0
  fi

  if ! ensure_dir "$HOME/bin"; then
    error "unable to create binary directory: $HOME/bin"
    return 1
  fi
  trap 'rm -f -- "${install_tmp:-}" "${marker_tmp:-}"' EXIT
  if [ ! -f "$installed" ] || [ -L "$installed" ] || [ ! -x "$installed" ] || ! cmp -s "$src" "$installed"; then
    if ! install_tmp="$(mktemp "$HOME/bin/.stinkpot.XXXXXX")"; then
      error "unable to stage stinkpot in $HOME/bin"
      return 1
    fi
    if ! install -m 0755 "$src" "$install_tmp"; then
      error "unable to stage bundled stinkpot executable"
      return 1
    fi
    if ! mv -f "$install_tmp" "$installed"; then
      error "unable to atomically install stinkpot: $installed"
      return 1
    fi
    install_tmp=""
  fi

  if [ -e "$marker" ]; then
    return 0
  fi

  if ! (
    umask 077
    trap 'rm -f -- "${marker_tmp:-}"' EXIT
    mkdir -p "$data_dir" || exit 1
    chmod 0700 "$data_dir" || exit 1
    "$installed" list >/dev/null || exit 1
    if [ ! -f "$db" ] || [ -L "$db" ]; then
      error "stinkpot did not initialize a regular database: $db"
      exit 1
    fi
    chmod 0600 "$db" || exit 1
    if [ -s "$legacy" ]; then
      "$installed" import --file "$legacy" || exit 1
      chmod 0600 "$db" || exit 1
    fi
    mkdir -p "$state_dir" || exit 1
    chmod 0700 "$state_dir" || exit 1
    marker_tmp="$(mktemp "$state_dir/.bash-history-import-v1.XXXXXX")" || exit 1
    : > "$marker_tmp" || exit 1
    chmod 0600 "$marker_tmp" || exit 1
    mv -f "$marker_tmp" "$marker" || exit 1
    marker_tmp=""
  ); then
    error "stinkpot Bash history migration failed"
    return 1
  fi
}
stinkpot_install
"""

_BASHRC = r"""if bin_exists stinkpot; then
  export HISTFILE=/dev/null
  eval "$(stinkpot init)"
else
  printf 'warning: stinkpot is unavailable; using Bash history defaults\n' >&2
fi
"""


@dataclass(frozen=True)
class Stinkpot:
    name: str = "stinkpot"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        artifacts = tuple(
            GeneratedBinary(
                name="stinkpot",
                dest=f"artifacts/stinkpot/{goos}-{goarch}/stinkpot",
                source_url=_SOURCE_URL,
                source_sha256=_SOURCE_SHA256,
                go_version=_GO_VERSION,
                goos=goos,
                goarch=goarch,
            )
            for goos, goarch in _TARGETS[env.os]
        )
        return Fragment(setup=_SETUP, bashrc=_BASHRC, artifacts=artifacts)
