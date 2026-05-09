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

# --- core_utils ---
component_begin "core_utils"
install_packages git jq ripgrep fd tree vim htop gnupg bash-completion

# --- helix ---
component_begin "helix"
install_package helix
install_config "$DIR/config/helix/config.toml" "$HOME/.config/helix/config.toml"

# --- starship ---
component_begin "starship"
ensure_dir "$HOME/.local/bin"
install_script starship https://starship.rs/install.sh -y -b "$HOME/.local/bin"
install_config "$DIR/config/starship/starship.toml" "$HOME/.config/starship.toml"

# --- zoxide ---
component_begin "zoxide"
install_package zoxide

# --- kubectl ---
component_begin "kubectl"
install_packages kubectl helm k9s kubectx

# --- python_tools ---
component_begin "python_tools"
install_script uv https://astral.sh/uv/install.sh

# --- claude_code ---
component_begin "claude_code"
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

# --- gh ---
component_begin "gh"
install_package gh
install_config "$DIR/config/gh/config.yml" "$HOME/.config/gh/config.yml"

# --- git_signing ---
component_begin "git_signing"
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

# --- rust ---
component_begin "rust"
install_script cargo https://sh.rustup.rs -y --default-toolchain stable

# --- node_fnm ---
component_begin "node_fnm"
install_script fnm https://fnm.vercel.app/install --skip-shell

# --- go_lang ---
component_begin "go_lang"
install_packages mercurial
if [ ! -s "$HOME/.gvm/scripts/gvm" ]; then
  install_script gvm https://raw.githubusercontent.com/moovweb/gvm/master/binscripts/gvm-installer
fi

# --- gcloud ---
component_begin "gcloud"
install_cask google-cloud-sdk

# --- aws ---
component_begin "aws"
install_package awscli
install_config "$DIR/config/aws/config" "$HOME/.aws/config"

# --- fonts ---
component_begin "fonts"
install_cask font-ubuntu
install_cask font-ubuntu-mono-nerd-font

# --- zed ---
component_begin "zed"
install_cask zed
install_config "$DIR/config/zed/settings.json" "$HOME/.config/zed/settings.json"
install_config "$DIR/config/zed/keymap.json" "$HOME/.config/zed/keymap.json"

# --- ghostty ---
component_begin "ghostty"
install_cask ghostty
install_config "$DIR/config/ghostty/config" "$HOME/Library/Application Support/com.mitchellh.ghostty/config"

# --- git_setup ---
component_begin "git_setup"
install_config_template "$DIR/config/git/gitconfig" "$HOME/.gitconfig" 'GIT_USER_NAME GIT_USER_EMAIL'
install_config "$DIR/config/git/gitignore_global" "$HOME/.gitignore_global"

# --- dotfiles_deploy ---
component_begin "dotfiles_deploy"
install_config "$DIR/.bashrc" "$HOME/.bashrc"
install_config "$DIR/alias.sh" "$HOME/.aliases"
install_config "$DIR/config/bash/bash_profile" "$HOME/.bash_profile"

if [ "$DOTGEN_MODE" = diff ]; then
  log "diff complete (no changes applied)"
else
  log "setup complete"
fi
