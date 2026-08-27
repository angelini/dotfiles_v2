#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${1-}" in
  deploy) ;;
  -h|--help|help)
    printf 'usage: %s deploy\n' "$0"
    printf '  deploy apply changes (overwrites configs)\n'
    exit 0 ;;
  "")
    printf 'usage: %s deploy\n' "$0" >&2; exit 2 ;;
  *)
    printf 'unknown mode: %s\nusage: %s deploy\n' "${1-}" "$0" >&2; exit 2 ;;
esac
source "$DIR/os_shim.sh"
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
update_pkg_index

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
  install_packages git git-delta just jq yq fzf ripgrep fd eza bat tree vim htop btop cloc gnupg bash-completion protobuf
); then
  component_end "core_utils" 0
else
  _rc=$?; component_end "core_utils" "$_rc"; exit "$_rc"
fi

# --- fzf_bash_history ---
component_begin "fzf_bash_history"
if (
  set -e
  history_file="$HOME/.bash_history"
  if [ -L "$history_file" ] || { [ -e "$history_file" ] && [ ! -f "$history_file" ]; }; then
    error "unsafe Bash history path (expected a regular non-symlink file): $history_file"
    exit 1
  fi
  if [ ! -e "$history_file" ]; then
    if ! (umask 077; set -o noclobber; : > "$history_file") 2>/dev/null; then
      error "unable to create Bash history file safely: $history_file"
      exit 1
    fi
  fi
  if [ -L "$history_file" ] || [ ! -f "$history_file" ]; then
    error "unsafe Bash history path (expected a regular non-symlink file): $history_file"
    exit 1
  fi
  if ! chmod 0600 "$history_file"; then
    error "unable to secure Bash history file: $history_file"
    exit 1
  fi
); then
  component_end "fzf_bash_history" 0
else
  _rc=$?; component_end "fzf_bash_history" "$_rc"; exit "$_rc"
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

# --- herdr ---
component_begin "herdr"
if (
  set -e
  _install_herdr() {
    local arch checksum remote_bin
    case "$(detect_arch)" in
      x86_64) arch=x86_64; checksum=ab50262c8190cd7aa9056d249d255c08c328c3e8716de9cfa29db4f131b8e2c1 ;;
      aarch64|arm64) arch=aarch64; checksum=a5d4f4d504d8b309c91f811050559300faba31258425f53c50852fc96f6ae574 ;;
      *) error "unsupported arch for Herdr: $(detect_arch)"; return 1 ;;
    esac
    download_bin_sha256 herdr "https://github.com/herdrdev/herdr/releases/download/v0.8.2/herdr-macos-${arch}" "$checksum" "0.8.2" --version
    ensure_dir "$HOME/.local/bin"
    remote_bin="$HOME/.local/bin/herdr"
    if [ -d "$remote_bin" ] || { [ -e "$remote_bin" ] && [ ! -f "$remote_bin" ] && [ ! -L "$remote_bin" ]; }; then
      error "unsafe Herdr remote binary destination: $remote_bin"
      return 1
    fi
    link_file "$HOME/bin/herdr" "$remote_bin"
    if [ ! -f "$remote_bin" ] || [ ! -x "$remote_bin" ]; then
      error "failed to publish Herdr remote binary: $remote_bin"
      return 1
    fi
    install_config "$DIR/config/herdr/config.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/config.toml"
    install -m 0755 "$DIR/config/herdr/herd-agent" "$HOME/.local/bin/herd-agent"
    "$remote_bin" plugin install "persiyanov/herdr-reviewr" --ref "v0.36.0" --yes
    "$remote_bin" plugin install "alexarthurs/herdr-sidebar/plugins/herdr-sidebar" --ref "v0.10.0" --yes
  }
  _install_herdr
); then
  component_end "herdr" 0
else
  _rc=$?; component_end "herdr" "$_rc"; exit "$_rc"
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
  install_config "$DIR/config/starship/starship.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/starship.toml"
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
    if [ -f "$HOME/.claude.json" ] && jq -e '.mcpServers.serena // empty' "$HOME/.claude.json" >/dev/null 2>&1; then
      return 0
    fi
    claude mcp add serena -s user -- serena start-mcp-server --context claude-code || true
  }
  install_config_dir "$DIR/config/claude" "$HOME/.claude" "claude" "settings.json"
  install_json_patch "$DIR/config/managed-settings/claude.json" "$HOME/.claude/settings.json" 0600
  install_config "$DIR/config/repositories/platform/CLAUDE.md" "$HOME/repos/platform/CLAUDE.md"
  _install_serena
  _register_serena_mcp
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
  gh extension install github/gh-stack
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
  install_script rustup https://sh.rustup.rs -y --default-toolchain stable
  [ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env"
  rustup target add wasm32-wasip2
); then
  component_end "rust" 0
else
  _rc=$?; component_end "rust" "$_rc"; exit "$_rc"
fi

# --- taplo ---
component_begin "taplo"
if (
  set -e
  _install_taplo() (
    local arch checksum installed tmp actual
    case "$(detect_arch)" in
      x86_64) arch=x86_64; checksum=9fd7a2872ea154df61a2c7e9ca69fc19ac08e29f2e2dc2f866e299bdc789c1a1 ;;
      aarch64|arm64) arch=aarch64; checksum=13cd257c1cadb003b40daf82b3fb1451e012e2463b760bdd33df07a07970c604 ;;
      *) error "unsupported arch for Taplo: $(detect_arch)"; exit 1 ;;
    esac
    installed="$HOME/bin/taplo"
    if [ -e "$installed" ] || [ -L "$installed" ]; then
      if [ ! -f "$installed" ] || [ -L "$installed" ]; then
        error "unsafe Taplo binary destination: $installed"
        exit 1
      fi
    fi
    if [ -x "$installed" ] && [ "$(sha256_file "$installed")" = "$checksum" ] && bin_version_matches "$installed" "0.10.0" --version; then
      exit 0
    fi
    ensure_dir "$HOME/bin"
    tmp="$(mktemp "$HOME/bin/.taplo.XXXXXX")"
    trap 'rm -f -- "$tmp"' EXIT
    curl -fsSL "https://github.com/tamasfe/taplo/releases/download/0.10.0/taplo-darwin-${arch}.gz" | gzip -dc > "$tmp"
    actual="$(sha256_file "$tmp")"
    if [ "$actual" != "$checksum" ]; then
      error "checksum mismatch for Taplo"
      exit 1
    fi
    chmod 0755 "$tmp"
    if ! bin_version_matches "$tmp" "0.10.0" --version; then
      error "version mismatch for Taplo"
      exit 1
    fi
    mv -f -- "$tmp" "$installed"
    tmp=""
  )
  _install_taplo
); then
  component_end "taplo" 0
else
  _rc=$?; component_end "taplo" "$_rc"; exit "$_rc"
fi

# --- zig ---
component_begin "zig"
if (
  set -e
  _install_zig() (
    local arch checksum zig_dir parent stage archive actual
    case "$(detect_arch)" in
      x86_64) arch=x86_64; checksum=0387557ed1877bc6a2e1802c8391953baddba76081876301c522f52977b52ba7 ;;
      aarch64|arm64) arch=aarch64; checksum=b23d70deaa879b5c2d486ed3316f7eaa53e84acf6fc9cc747de152450d401489 ;;
      *) error "unsupported arch for Zig: $(detect_arch)"; exit 1 ;;
    esac
    zig_dir="$HOME/.local/share/zig"
    if [ -e "$zig_dir" ] || [ -L "$zig_dir" ]; then
      if [ ! -d "$zig_dir" ] || [ -L "$zig_dir" ]; then
        error "unsafe Zig installation destination: $zig_dir"
        exit 1
      fi
    fi
    if [ -x "$zig_dir/zig" ] && [ "$("$zig_dir/zig" version)" = "0.16.0" ]; then
      exit 0
    fi
    parent="$HOME/.local/share"
    ensure_dir "$parent"
    stage="$(mktemp -d "$parent/.zig.XXXXXX")"
    archive="$(mktemp "$parent/.zig-archive.XXXXXX")"
    trap 'rm -rf -- "$stage"; rm -f -- "$archive"' EXIT
    curl -fsSL "https://ziglang.org/download/0.16.0/zig-${arch}-macos-0.16.0.tar.xz" -o "$archive"
    actual="$(sha256_file "$archive")"
    if [ "$actual" != "$checksum" ]; then
      error "checksum mismatch for Zig"
      exit 1
    fi
    tar -xJf "$archive" -C "$stage" --strip-components=1
    if [ ! -x "$stage/zig" ] || [ "$("$stage/zig" version)" != "0.16.0" ]; then
      error "version mismatch for Zig"
      exit 1
    fi
    rm -rf -- "$zig_dir"
    mv -- "$stage" "$zig_dir"
    stage=""
  )
  _install_zig
); then
  component_end "zig" 0
else
  _rc=$?; component_end "zig" "$_rc"; exit "$_rc"
fi

# --- node_fnm ---
component_begin "node_fnm"
if (
  set -e
  install_package unzip
  install_script fnm https://fnm.vercel.app/install --skip-shell --force-install --install-dir "$HOME/.local/share/fnm"
  fnm_bin="$(command -v fnm 2>/dev/null || true)"
  if [ -z "$fnm_bin" ]; then
    fnm_bin="$HOME/.local/share/fnm/fnm"
  fi
  if [ ! -x "$fnm_bin" ]; then
    error "fnm installer completed; fnm unavailable"
    exit 1
  fi
  eval "$("$fnm_bin" env --shell bash)"
  "$fnm_bin" install --lts --use
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
  install -m 0755 "$DIR/config/pi/launcher/pi.sh" "$HOME/.local/bin/pi"
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
  install_package gnupg
  if ! bin_exists doppler; then
    install_package dopplerhq/cli/doppler
  fi
); then
  component_end "doppler" 0
else
  _rc=$?; component_end "doppler" "$_rc"; exit "$_rc"
fi

# --- fonts ---
component_begin "fonts"
if (
  set -e
  if [ ! -f "$HOME/Library/Fonts/Ubuntu-Regular.ttf" ]; then
    install_cask font-ubuntu
  fi
  if [ ! -f "$HOME/Library/Fonts/UbuntuMonoNerdFont-Regular.ttf" ]; then
    install_cask font-ubuntu-mono-nerd-font
  fi
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

# --- orbstack ---
component_begin "orbstack"
if (
  set -e
  install_cask orbstack
); then
  component_end "orbstack" 0
else
  _rc=$?; component_end "orbstack" "$_rc"; exit "$_rc"
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
  private_dotfiles_installer="$HOME/repos/dotfiles-private/install.sh"
  if [ -r "$private_dotfiles_installer" ]; then
    PATH="$HOME/.local/bin:$(printenv PATH)" bash "$private_dotfiles_installer"
  fi
); then
  component_end "dotfiles_deploy" 0
else
  _rc=$?; component_end "dotfiles_deploy" "$_rc"; exit "$_rc"
fi

log "setup complete"
