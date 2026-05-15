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
      chsh -s /opt/homebrew/bin/bash
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
  install_packages git jq yq fzf ripgrep fd tree vim htop cloc gnupg bash-completion
); then
  component_end "core_utils" 0
else
  _rc=$?; component_end "core_utils" "$_rc"; exit "$_rc"
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
  install_config "$DIR/config/claude/settings.json" "$HOME/.claude/settings.json"
  install_config "$DIR/config/claude/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
  install_config "$DIR/config/claude/hooks/serena-reminder.sh" "$HOME/.claude/hooks/serena-reminder.sh"
  if [ "$DOTGEN_MODE" = deploy ]; then
    chmod +x "$HOME/.claude/hooks/serena-reminder.sh"
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
  install_script fnm https://fnm.vercel.app/install --skip-shell
); then
  component_end "node_fnm" 0
else
  _rc=$?; component_end "node_fnm" "$_rc"; exit "$_rc"
fi

# --- pi_agent ---
component_begin "pi_agent"
if (
  set -e
  install_npm_global @earendil-works/pi-coding-agent
  install_npm_global pi-lens
  install_npm_global pi-mcp-adapter
  install_npm_global pi-subagents
  install_npm_global pi-web-access
  install_npm_global pi-simplify
  install_npm_global @juicesharp/rpiv-ask-user-question
  install_npm_global @juicesharp/rpiv-todo
  install_npm_global @samfp/pi-memory
  ensure_dir "$HOME/.pi/agent"
  install_config "$DIR/config/pi/agent/settings.json" "$HOME/.pi/agent/settings.json"
  install_config_template "$DIR/config/pi/agent/models.json" "$HOME/.pi/agent/models.json" "GOOGLE_GENERATIVE_AI_API_KEY"
  install_config "$DIR/config/pi/agent/web-search.json" "$HOME/.pi/agent/web-search.json"
  install_config "$DIR/config/pi/agent/AGENTS.md" "$HOME/.pi/agent/AGENTS.md"
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
