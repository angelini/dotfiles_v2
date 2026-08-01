#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOTGEN_MODE="${1-}"
case "$DOTGEN_MODE" in
  diff|deploy) ;;
  -h|--help|help)
    printf 'usage: %s {diff|deploy}\n' "$0"
    printf '  diff   show pending changes (read-only)\n'
    printf '  deploy apply changes (overwrites configs)\n'
    exit 0 ;;
  "")
    printf 'usage: %s {diff|deploy}\n' "$0" >&2; exit 2 ;;
  *)
    printf 'unknown mode: %s\nusage: %s {diff|deploy}\n' "$DOTGEN_MODE" "$0" >&2; exit 2 ;;
esac
export DOTGEN_MODE
source "$DIR/os_shim.sh"
if [ "$DOTGEN_MODE" = deploy ]; then
  if [ "$(id -u)" -eq 0 ]; then
    error "deploy must run as a regular user, not root"
    exit 2
  fi
  if ! bin_exists sudo; then
    error "deploy requires sudo"
    exit 2
  fi
  if ! sudo -v; then
    error "unable to authenticate with sudo"
    exit 2
  fi
  bin_exists envsubst || install_package gettext
  if [ ! -r "${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/secrets.env" ]; then
    error "deploy requires ${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/secrets.env"
    error "copy from: $DIR/config/dotgen/secrets.env.template"
    exit 2
  fi
fi
[ "$DOTGEN_MODE" = deploy ] && update_pkg_index

# --- bash_base ---
component_begin "bash_base"
if (
  set -e
  if [ "$(detect_os)" = macos ]; then
    install_package bash
    if ! grep -q "/opt/homebrew/bin/bash" /etc/shells; then
      log "adding homebrew bash to /etc/shells"
      echo "/opt/homebrew/bin/bash" | sudo tee -a /etc/shells >/dev/null
    fi
    if [ "$SHELL" != "/opt/homebrew/bin/bash" ]; then
      log "changing shell to homebrew bash"
      sudo chsh -s /opt/homebrew/bin/bash "$(whoami)"
    fi
  fi
); then
  component_end "bash_base" 0
else
  _rc=$?; component_end "bash_base" "$_rc"; exit "$_rc"
fi

# --- core_utils ---
component_begin "core_utils"
if (
  set -e
  install_packages git git-delta jq yq fzf ripgrep fd eza bat tree vim htop btop cloc gnupg bash-completion
); then
  component_end "core_utils" 0
else
  _rc=$?; component_end "core_utils" "$_rc"; exit "$_rc"
fi

# --- stinkpot ---
component_begin "stinkpot"
if (
  set -e
  stinkpot_install() {
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
); then
  component_end "stinkpot" 0
else
  _rc=$?; component_end "stinkpot" "$_rc"; exit "$_rc"
fi

# --- tmux ---
component_begin "tmux"
if (
  set -e
  install_package tmux
  install_config "$DIR/config/tmux/tmux.conf" "$HOME/.tmux.conf"
); then
  component_end "tmux" 0
else
  _rc=$?; component_end "tmux" "$_rc"; exit "$_rc"
fi

# --- mosh ---
component_begin "mosh"
if (
  set -e
  install_package mosh
); then
  component_end "mosh" 0
else
  _rc=$?; component_end "mosh" "$_rc"; exit "$_rc"
fi

# --- helix ---
component_begin "helix"
if (
  set -e
  install_package helix
  install_config "$DIR/config/helix/config.toml" "$HOME/.config/helix/config.toml"
); then
  component_end "helix" 0
else
  _rc=$?; component_end "helix" "$_rc"; exit "$_rc"
fi

# --- starship ---
component_begin "starship"
if (
  set -e
  ensure_dir "$HOME/.local/bin"
  install_script starship https://starship.rs/install.sh -y -b "$HOME/.local/bin"
  install_config "$DIR/config/starship/starship.toml" "$HOME/.config/starship.toml"
); then
  component_end "starship" 0
else
  _rc=$?; component_end "starship" "$_rc"; exit "$_rc"
fi

# --- shellcheck ---
component_begin "shellcheck"
if (
  set -e
  install_package shellcheck
); then
  component_end "shellcheck" 0
else
  _rc=$?; component_end "shellcheck" "$_rc"; exit "$_rc"
fi

# --- zoxide ---
component_begin "zoxide"
if (
  set -e
  install_package zoxide
); then
  component_end "zoxide" 0
else
  _rc=$?; component_end "zoxide" "$_rc"; exit "$_rc"
fi

# --- kubectl ---
component_begin "kubectl"
if (
  set -e
  install_packages kubectl helm k9s kubectx kubie
); then
  component_end "kubectl" 0
else
  _rc=$?; component_end "kubectl" "$_rc"; exit "$_rc"
fi

# --- python_tools ---
component_begin "python_tools"
if (
  set -e
  install_script uv https://astral.sh/uv/install.sh
); then
  component_end "python_tools" 0
else
  _rc=$?; component_end "python_tools" "$_rc"; exit "$_rc"
fi

# --- claude_code ---
component_begin "claude_code"
if (
  set -e
  export PATH="$HOME/.local/bin:$PATH"
  install_script claude https://claude.ai/install.sh
  _install_serena() {
    local uv_bin
    uv_bin="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"
    if [ ! -x "$uv_bin" ]; then
      error "_install_serena: uv not found"
      return 1
    fi
    if "$uv_bin" tool list 2>/dev/null | grep -q '^serena-agent'; then
      return 0
    fi
    "$uv_bin" tool install --from https://github.com/oraios/serena/archive/refs/heads/main.tar.gz serena-agent
  }
  _register_serena_mcp() {
    if ! bin_exists claude; then
      return 0
    fi
    if claude mcp list 2>/dev/null | grep -q '^serena'; then
      return 0
    fi
    claude mcp add serena -s user -- serena start-mcp-server --context claude-code || true
  }
  install_config_dir "$DIR/config/claude" "$HOME/.claude" "claude" "settings.json"
  install_json_patch "$DIR/config/managed-settings/claude.json" "$HOME/.claude/settings.json" 0600
  if [ "$DOTGEN_MODE" = deploy ]; then
    _install_serena
    _register_serena_mcp
  fi
); then
  component_end "claude_code" 0
else
  _rc=$?; component_end "claude_code" "$_rc"; exit "$_rc"
fi

# --- gh ---
component_begin "gh"
if (
  set -e
  install_package gh
  install_config "$DIR/config/gh/config.yml" "$HOME/.config/gh/config.yml"
); then
  component_end "gh" 0
else
  _rc=$?; component_end "gh" "$_rc"; exit "$_rc"
fi

# --- git_signing ---
component_begin "git_signing"
if (
  set -e
  ensure_dir "$HOME/.ssh"
  chmod 700 "$HOME/.ssh"
  if [ ! -f "$HOME/.ssh/id_signing" ]; then
    ssh-keygen -t ed25519 -a 100 -N "" \
      -C "$(detect_os)-$(hostname)-signing" \
      -f "$HOME/.ssh/id_signing"
  fi
  if bin_exists gh && gh auth status >/dev/null 2>&1; then
    _sig_key="$(awk '{print $2}' "$HOME/.ssh/id_signing.pub")"
    if ! gh ssh-key list 2>/dev/null | grep -qF "$_sig_key"; then
      gh ssh-key add "$HOME/.ssh/id_signing.pub" \
        --type signing \
        --title "$(detect_os)-$(hostname)-signing"
    fi
    unset _sig_key
  else
    log "gh not authed; after 'gh auth login' run: gh ssh-key add ~/.ssh/id_signing.pub --type signing"
  fi
); then
  component_end "git_signing" 0
else
  _rc=$?; component_end "git_signing" "$_rc"; exit "$_rc"
fi

# --- rust ---
component_begin "rust"
if (
  set -e
  install_script cargo https://sh.rustup.rs -y --default-toolchain stable
); then
  component_end "rust" 0
else
  _rc=$?; component_end "rust" "$_rc"; exit "$_rc"
fi

# --- node_fnm ---
component_begin "node_fnm"
if (
  set -e
  install_package unzip
  install_script fnm https://fnm.vercel.app/install --skip-shell --force-install --install-dir "$HOME/.local/share/fnm"
  if [ "$DOTGEN_MODE" = deploy ]; then
    fnm_bin="$HOME/.local/share/fnm/fnm"
    if [ ! -x "$fnm_bin" ]; then
      error "fnm installer completed; fnm unavailable"
      exit 1
    fi
    eval "$("$fnm_bin" env --shell bash)"
    "$fnm_bin" install --lts --use
  fi
); then
  component_end "node_fnm" 0
else
  _rc=$?; component_end "node_fnm" "$_rc"; exit "$_rc"
fi

# --- npm_config ---
component_begin "npm_config"
if (
  set -e
  install_config_template "$DIR/config/npm/npmrc" "$HOME/.npmrc" 'NPM_TOKEN' 0600
); then
  component_end "npm_config" 0
else
  _rc=$?; component_end "npm_config" "$_rc"; exit "$_rc"
fi

# --- pi_agent ---
component_begin "pi_agent"
if (
  set -e
  install_npm_global @earendil-works/pi-coding-agent pi-lens pi-mcp-adapter pi-subagents pi-simplify @plannotator/pi-extension @dreki-gg/pi-context7 @juicesharp/rpiv-ask-user-question @juicesharp/rpiv-btw @juicesharp/rpiv-todo @samfp/pi-memory @vanillagreen/pi-web-tools
  ensure_dir "$HOME/.pi/agent"
  ensure_dir "$HOME/.config/pi/sandbox"
  ensure_dir "$HOME/.local/bin"
  install_config_dir "$DIR/config/pi/agent" "$HOME/.pi/agent" "pi-agent" "settings.json"
  install_json_patch "$DIR/config/managed-settings/pi.json" "$HOME/.pi/agent/settings.json" 0600
  install_config "$DIR/config/pi/sandbox/pi-macos.sb" "$HOME/.config/pi/sandbox/pi-macos.sb"
  install -m 0755 "$DIR/config/pi/sandbox/pi-sandbox.sh" "$HOME/.local/bin/pi-sandbox"

  install_config_dir "$DIR/config/pi-angelini" "$HOME/repos/pi-angelini"
); then
  component_end "pi_agent" 0
else
  _rc=$?; component_end "pi_agent" "$_rc"; exit "$_rc"
fi

# --- postgres ---
component_begin "postgres"
if (
  set -e
  install_package postgresql@18
); then
  component_end "postgres" 0
else
  _rc=$?; component_end "postgres" "$_rc"; exit "$_rc"
fi

# --- go_lang ---
component_begin "go_lang"
if (
  set -e
  install_packages mercurial
  GO_VERSION="1.25.5"
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
); then
  component_end "go_lang" 0
else
  _rc=$?; component_end "go_lang" "$_rc"; exit "$_rc"
fi

# --- gcloud ---
component_begin "gcloud"
if (
  set -e
  install_cask google-cloud-sdk
); then
  component_end "gcloud" 0
else
  _rc=$?; component_end "gcloud" "$_rc"; exit "$_rc"
fi

# --- aws ---
component_begin "aws"
if (
  set -e
  install_package awscli
  install_config "$DIR/config/aws/config" "$HOME/.aws/config"
); then
  component_end "aws" 0
else
  _rc=$?; component_end "aws" "$_rc"; exit "$_rc"
fi

# --- doppler ---
component_begin "doppler"
if (
  set -e
  install_packages gnupg dopplerhq/cli/doppler
); then
  component_end "doppler" 0
else
  _rc=$?; component_end "doppler" "$_rc"; exit "$_rc"
fi

# --- fonts ---
component_begin "fonts"
if (
  set -e
  install_cask font-ubuntu
  install_cask font-ubuntu-mono-nerd-font
); then
  component_end "fonts" 0
else
  _rc=$?; component_end "fonts" "$_rc"; exit "$_rc"
fi

# --- ghostty ---
component_begin "ghostty"
if (
  set -e
  install_cask ghostty
  install_config "$DIR/config/ghostty/config" "$HOME/Library/Application Support/com.mitchellh.ghostty/config"
); then
  component_end "ghostty" 0
else
  _rc=$?; component_end "ghostty" "$_rc"; exit "$_rc"
fi

# --- zed ---
component_begin "zed"
if (
  set -e
  install_cask zed
  install_config "$DIR/config/zed/settings.json" "$HOME/.config/zed/settings.json"
  install_config "$DIR/config/zed/keymap.json" "$HOME/.config/zed/keymap.json"
); then
  component_end "zed" 0
else
  _rc=$?; component_end "zed" "$_rc"; exit "$_rc"
fi

# --- supacode ---
component_begin "supacode"
if (
  set -e
  install_cask supacode
); then
  component_end "supacode" 0
else
  _rc=$?; component_end "supacode" "$_rc"; exit "$_rc"
fi

# --- git_setup ---
component_begin "git_setup"
if (
  set -e
  install_config_template "$DIR/config/git/gitconfig" "$HOME/.gitconfig" 'GIT_USER_NAME GIT_USER_EMAIL'
  install_config "$DIR/config/git/gitignore_global" "$HOME/.gitignore_global"
); then
  component_end "git_setup" 0
else
  _rc=$?; component_end "git_setup" "$_rc"; exit "$_rc"
fi

# --- dotfiles_deploy ---
component_begin "dotfiles_deploy"
if (
  set -e
  install_config "$DIR/.bashrc" "$HOME/.bashrc"
  install_config "$DIR/alias.sh" "$HOME/.aliases"
  install_config "$DIR/config/bash/bash_profile" "$HOME/.bash_profile"
); then
  component_end "dotfiles_deploy" 0
else
  _rc=$?; component_end "dotfiles_deploy" "$_rc"; exit "$_rc"
fi

if [ "$DOTGEN_MODE" = deploy ]; then
  log "setup complete"
fi
