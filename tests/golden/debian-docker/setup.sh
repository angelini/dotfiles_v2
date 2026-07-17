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

# --- core_utils ---
component_begin "core_utils"
if (
  set -e
  install_packages git jq yq fzf ripgrep fd-find tree vim htop cloc gnupg2 bash-completion bsdmainutils
  ensure_dir "$HOME/bin"
  if bin_exists fdfind && ! bin_exists fd; then
    ln -sf "$(command -v fdfind)" "$HOME/bin/fd"
  fi
); then
  component_end "core_utils" 0
else
  _rc=$?; component_end "core_utils" "$_rc"; exit "$_rc"
fi

# --- helix ---
component_begin "helix"
if (
  set -e
  _install_helix_linux() {
    local tarch tmp dir
    case "$(detect_arch)" in
      x86_64) tarch=x86_64 ;;
      aarch64|arm64) tarch=aarch64 ;;
      *) error "unsupported arch for helix: $(detect_arch)"; return 1 ;;
    esac
    install_package xz-utils
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
  _kubie_arch() {
    case "$(detect_arch)" in
      x86_64) echo amd64 ;;
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
  _install_kubie_linux() {
    local arch
    arch="$(_kubie_arch)"
    download_bin kubie "https://github.com/sbstp/kubie/releases/download/v0.27.0/kubie-linux-${arch}"
  }
  _install_kubectl_linux
  _install_helm_linux
  _install_k9s_linux
  _install_kubectx_linux
  _install_kubens_linux
  _install_kubie_linux
); then
  component_end "kubectl" 0
else
  _rc=$?; component_end "kubectl" "$_rc"; exit "$_rc"
fi

# --- gh ---
component_begin "gh"
if (
  set -e
  add_repo apt githubcli "deb [signed-by=/etc/apt/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" "https://cli.github.com/packages/githubcli-archive-keyring.gpg"
  update_pkg_index
  install_package gh
  install_config "$DIR/config/gh/config.yml" "$HOME/.config/gh/config.yml"
); then
  component_end "gh" 0
else
  _rc=$?; component_end "gh" "$_rc"; exit "$_rc"
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

# --- pi_agent ---
component_begin "pi_agent"
if (
  set -e
  install_package bubblewrap
  install_npm_global @earendil-works/pi-coding-agent
  install_npm_global pi-lens
  install_npm_global pi-mcp-adapter
  install_npm_global pi-subagents
  install_npm_global pi-simplify
  install_npm_global @plannotator/pi-extension
  install_npm_global @dreki-gg/pi-context7
  install_npm_global @juicesharp/rpiv-ask-user-question
  install_npm_global @juicesharp/rpiv-btw
  install_npm_global @juicesharp/rpiv-todo
  install_npm_global @samfp/pi-memory
  install_npm_global @vanillagreen/pi-web-tools
  ensure_dir "$HOME/.pi/agent"
  ensure_dir "$HOME/.config/pi/sandbox"
  ensure_dir "$HOME/.local/bin"
  install_config "$DIR/config/pi/agent/settings.json" "$HOME/.pi/agent/settings.json"
  install_config "$DIR/config/pi/agent/models.json" "$HOME/.pi/agent/models.json"
  install_config "$DIR/config/pi/agent/web-search.json" "$HOME/.pi/agent/web-search.json"
  install_config "$DIR/config/pi/agent/AGENTS.md" "$HOME/.pi/agent/AGENTS.md"
  install_config "$DIR/config/pi/agent/plannotator.json" "$HOME/.pi/agent/plannotator.json"
  install_config "$DIR/config/pi/agent/extensions/supacode/index.ts" "$HOME/.pi/agent/extensions/supacode/index.ts"
  install_config "$DIR/config/pi/agent/skills/supacode-cli/SKILL.md" "$HOME/.pi/agent/skills/supacode-cli/SKILL.md"
  install_config "$DIR/config/pi/agent/agents/claude-pipeline/architect.md" "$HOME/.pi/agent/agents/claude-pipeline/architect.md"
  install_config "$DIR/config/pi/agent/agents/claude-pipeline/editor.md" "$HOME/.pi/agent/agents/claude-pipeline/editor.md"
  install_config "$DIR/config/pi/agent/agents/claude-pipeline/planner.md" "$HOME/.pi/agent/agents/claude-pipeline/planner.md"
  install_config "$DIR/config/pi/agent/agents/claude-pipeline/reviewer.md" "$HOME/.pi/agent/agents/claude-pipeline/reviewer.md"
  install_config "$DIR/config/pi/agent/agents/claude-pipeline/scout.md" "$HOME/.pi/agent/agents/claude-pipeline/scout.md"
  install_config "$DIR/config/pi/agent/chains/pipeline.chain.md" "$HOME/.pi/agent/chains/pipeline.chain.md"
  install_config "$DIR/config/pi/agent/prompts/pipeline.md" "$HOME/.pi/agent/prompts/pipeline.md"
  install_config "$DIR/config/pi/sandbox/pi-macos.sb" "$HOME/.config/pi/sandbox/pi-macos.sb"
  install -m 0755 "$DIR/config/pi/sandbox/pi-sandbox.sh" "$HOME/.local/bin/pi-sandbox"

  _install_pi_angelini() {
    local src="$DIR/config/pi-angelini" dst="$HOME/repos/pi-angelini"
    if [ "$DOTGEN_MODE" = diff ]; then
      if [ ! -d "$dst" ]; then
        printf '+ COPY   %s\n' "$dst"
      elif ! diff -qr -x .git -x node_modules -x .pytest_cache "$src" "$dst" >/dev/null 2>&1; then
        printf '~ SYNC   %s\n' "$dst"
      fi
      return 0
    fi

    ensure_dir "$HOME/repos"
    if [ -d "$dst/.git" ]; then
      cp -R "$src"/. "$dst"/
      return 0
    fi

    rm -rf "$dst"
    ensure_dir "$dst"
    cp -R "$src"/. "$dst"/
  }
  _install_pi_angelini
); then
  component_end "pi_agent" 0
else
  _rc=$?; component_end "pi_agent" "$_rc"; exit "$_rc"
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
