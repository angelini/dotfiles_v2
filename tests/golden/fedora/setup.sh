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
install_packages git jq ripgrep fd-find tree vim htop gnupg2 bash-completion

# --- helix ---
component_begin "helix"
_install_helix_linux() {
  local tarch tmp dir
  case "$(detect_arch)" in
    x86_64) tarch=x86_64 ;;
    aarch64|arm64) tarch=aarch64 ;;
    *) error "unsupported arch for helix: $(detect_arch)"; return 1 ;;
  esac
  install_package xz
  tmp="$(mktemp -d)"
  dir="helix-25.07.1-${tarch}-linux"
  curl -fsSL "https://github.com/helix-editor/helix/releases/download/25.07.1/${dir}.tar.xz" \
    | tar -xJ -C "$tmp"
  ensure_dir "$HOME/bin"
  install -m 0755 "$tmp/$dir/hx" "$HOME/bin/hx"
  ensure_dir "$HOME/.config/helix"
  rm -rf "$HOME/.config/helix/runtime"
  cp -r "$tmp/$dir/runtime" "$HOME/.config/helix/runtime"
  rm -rf "$tmp"
}
if ! bin_exists hx; then
  _install_helix_linux
fi
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
_kube_arch() {
  case "$(detect_arch)" in
    x86_64) echo amd64 ;;
    aarch64|arm64) echo arm64 ;;
    *) error "unsupported arch: $(detect_arch)"; return 1 ;;
  esac
}
_kubectx_arch() {
  case "$(detect_arch)" in
    x86_64) echo x86_64 ;;
    aarch64|arm64) echo arm64 ;;
    *) error "unsupported arch: $(detect_arch)"; return 1 ;;
  esac
}
_install_kubectl_linux() {
  local arch
  arch="$(_kube_arch)"
  download_bin kubectl "https://dl.k8s.io/release/v1.35.4/bin/linux/${arch}/kubectl"
}
_install_helm_linux() {
  local arch
  arch="$(_kube_arch)"
  download_tar_bin helm "https://get.helm.sh/helm-v3.20.2-linux-${arch}.tar.gz" "linux-${arch}/helm"
}
_install_k9s_linux() {
  local arch
  arch="$(_kube_arch)"
  download_tar_bin k9s "https://github.com/derailed/k9s/releases/latest/download/k9s_Linux_${arch}.tar.gz" "k9s"
}
_install_kubectx_linux() {
  local arch
  arch="$(_kubectx_arch)"
  download_tar_bin kubectx "https://github.com/ahmetb/kubectx/releases/download/v0.11.0/kubectx_v0.11.0_linux_${arch}.tar.gz" "kubectx"
}
_install_kubens_linux() {
  local arch
  arch="$(_kubectx_arch)"
  download_tar_bin kubens "https://github.com/ahmetb/kubectx/releases/download/v0.11.0/kubens_v0.11.0_linux_${arch}.tar.gz" "kubens"
}
_install_kubectl_linux
_install_helm_linux
_install_k9s_linux
_install_kubectx_linux
_install_kubens_linux

# --- python_tools ---
component_begin "python_tools"
install_packages gcc gcc-c++ openssl-devel libffi-devel
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
install_packages curl git make bison gcc glibc-devel
if [ ! -s "$HOME/.gvm/scripts/gvm" ]; then
  install_script gvm https://raw.githubusercontent.com/moovweb/gvm/master/binscripts/gvm-installer
fi

# --- gcloud ---
component_begin "gcloud"
add_repo dnf google-cloud-cli "[google-cloud-cli]
name=Google Cloud CLI
baseurl=https://packages.cloud.google.com/yum/repos/cloud-sdk-el9-\$basearch
enabled=1
gpgcheck=1
repo_gpgcheck=0
gpgkey=https://packages.cloud.google.com/yum/doc/rpm-package-key.gpg
"
install_package google-cloud-cli

# --- aws ---
component_begin "aws"
_install_awscli_linux() {
  local arch zip_arch tmp
  arch="$(detect_arch)"
  case "$arch" in
    x86_64) zip_arch=x86_64 ;;
    aarch64|arm64) zip_arch=aarch64 ;;
    *) error "unsupported arch for awscli: $arch"; return 1 ;;
  esac
  tmp="$(mktemp -d)"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${zip_arch}.zip" -o "$tmp/awscli.zip"
  unzip -q "$tmp/awscli.zip" -d "$tmp"
  sudo "$tmp/aws/install" --update
  rm -rf "$tmp"
}
if ! bin_exists aws; then
  _install_awscli_linux
fi
install_config "$DIR/config/aws/config" "$HOME/.aws/config"

# --- fonts ---
component_begin "fonts"
install_package ubuntu-family-fonts

# --- zed ---
component_begin "zed"
install_script zed https://zed.dev/install.sh
install_config "$DIR/config/zed/settings.json" "$HOME/.config/zed/settings.json"
install_config "$DIR/config/zed/keymap.json" "$HOME/.config/zed/keymap.json"

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
