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

# --- core_utils ---
component_begin "core_utils"
if (
  set -e
  install_packages git git-delta just jq yq fzf ripgrep fd-find eza bat tree vim htop btop cloc gnupg2 bash-completion bsdmainutils
  if bin_exists fdfind && ! bin_exists fd; then
    link_file "$(command -v fdfind)" "$HOME/bin/fd"
  fi
  if bin_exists batcat && ! bin_exists bat; then
    link_file "$(command -v batcat)" "$HOME/bin/bat"
  fi
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
  install_config "$DIR/config/starship/starship.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/starship.toml"
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
    download_bin kubectl "https://dl.k8s.io/release/v1.35.4/bin/linux/${arch}/kubectl" "v1.35.4" version --client
  }
  _install_helm_linux() {
    local arch
    arch="$(_kube_arch)"
    download_tar_bin helm "https://get.helm.sh/helm-v3.20.2-linux-${arch}.tar.gz" "linux-${arch}/helm" "v3.20.2" version --template '{{.Version}}'
  }
  _install_k9s_linux() {
    local arch
    arch="$(_kube_arch)"
    download_tar_bin k9s "https://github.com/derailed/k9s/releases/download/v0.51.0/k9s_Linux_${arch}.tar.gz" "k9s" "v0.51.0" version --short
  }
  _install_kubectx_linux() {
    local arch
    arch="$(_kubectx_arch)"
    download_tar_bin kubectx "https://github.com/ahmetb/kubectx/releases/download/v0.11.0/kubectx_v0.11.0_linux_${arch}.tar.gz" "kubectx" "v0.11.0" --version
  }
  _install_kubens_linux() {
    local arch
    arch="$(_kubectx_arch)"
    download_tar_bin kubens "https://github.com/ahmetb/kubectx/releases/download/v0.11.0/kubens_v0.11.0_linux_${arch}.tar.gz" "kubens" "v0.11.0" --version
  }
  _install_kubie_linux() {
    local arch
    arch="$(_kubie_arch)"
    download_bin kubie "https://github.com/sbstp/kubie/releases/download/v0.27.0/kubie-linux-${arch}" "0.27.0" --version
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
  gh extension install github/gh-stack
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
  install_package bubblewrap
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
