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
  install_packages git git-delta jq yq fzf ripgrep fd-find eza bat tree vim htop btop cloc gnupg2 bash-completion bsdmainutils
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

# --- python_tools ---
component_begin "python_tools"
if (
  set -e
  install_packages build-essential libssl-dev libffi-dev
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
  add_repo apt githubcli "deb [signed-by=/etc/apt/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" "https://cli.github.com/packages/githubcli-archive-keyring.gpg"
  update_pkg_index
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
  codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  add_repo apt pgdg "deb [signed-by=/etc/apt/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt ${codename}-pgdg main" "https://www.postgresql.org/media/keys/ACCC4CF8.asc"
  update_pkg_index
  install_package postgresql-18
); then
  component_end "postgres" 0
else
  _rc=$?; component_end "postgres" "$_rc"; exit "$_rc"
fi

# --- go_lang ---
component_begin "go_lang"
if (
  set -e
  install_packages curl git make bison gcc libc6-dev
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
  add_repo apt google-cloud-sdk \
    "deb [signed-by=/etc/apt/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    "https://packages.cloud.google.com/apt/doc/apt-key.gpg"
  update_pkg_index
  install_package google-cloud-cli
); then
  component_end "gcloud" 0
else
  _rc=$?; component_end "gcloud" "$_rc"; exit "$_rc"
fi

# --- aws ---
component_begin "aws"
if (
  set -e
  install_package unzip
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
); then
  component_end "aws" 0
else
  _rc=$?; component_end "aws" "$_rc"; exit "$_rc"
fi

# --- doppler ---
component_begin "doppler"
if (
  set -e
  install_packages apt-transport-https ca-certificates curl gnupg
  add_repo apt doppler-cli "deb [signed-by=/etc/apt/keyrings/doppler-cli.gpg] https://packages.doppler.com/public/cli/deb/debian any-version main" "https://packages.doppler.com/public/cli/gpg.DE2A7741A397C129.key"
  update_pkg_index
  install_package doppler
); then
  component_end "doppler" 0
else
  _rc=$?; component_end "doppler" "$_rc"; exit "$_rc"
fi

# --- fonts ---
component_begin "fonts"
if (
  set -e
  install_packages fontconfig xz-utils
  _install_nerd_fonts() {
    local tmp url
    tmp="$(mktemp -d)"
    url="https://github.com/ryanoasis/nerd-fonts/releases/download/v3.3.0/UbuntuMono.tar.xz"
    curl -fsSL "$url" -o "$tmp/fonts.tar.xz"
    mkdir -p "$HOME/.local/share/fonts"
    tar -xf "$tmp/fonts.tar.xz" -C "$HOME/.local/share/fonts"
    fc-cache -f
    rm -rf "$tmp"
  }
  if [ ! -d "$HOME/.local/share/fonts/UbuntuMono" ]; then
    _install_nerd_fonts
  fi
); then
  component_end "fonts" 0
else
  _rc=$?; component_end "fonts" "$_rc"; exit "$_rc"
fi

# --- tmuxinator ---
component_begin "tmuxinator"
if (
  set -e
  install_package tmuxinator
  install_config "$DIR/config/tmuxinator/default.yml" "${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/tmuxinator/default.yml"

  install_tmuxinator_helper() {
    local src="$DIR/config/tmuxinator/dotgen-agent-session"
    local dst="/usr/local/bin/dotgen-agent-session"
    if [ ! -f "$src" ] || [ -L "$src" ] || [ ! -x "$src" ]; then
      error "invalid bundled tmuxinator helper: $src"
      return 1
    fi
    if [ -e "$dst" ] || [ -L "$dst" ]; then
      if [ ! -f "$dst" ] || [ -L "$dst" ]; then
        error "unsafe tmuxinator helper destination: $dst"
        return 1
      fi
    fi
    if [ -e "$dst" ] && cmp -s "$src" "$dst" && [ "$(stat -c '%a' "$dst")" = 755 ]; then
      return 0
    fi
    sudo install -m 0755 "$src" "$dst"
  }
  install_tmuxinator_helper
); then
  component_end "tmuxinator" 0
else
  _rc=$?; component_end "tmuxinator" "$_rc"; exit "$_rc"
fi

# --- docker ---
component_begin "docker"
if (
  set -e
  _docker_fail() {
    error "$1"
    return 1
  }

  _docker_validate_subids() {
    local file="$1" username="$2" numeric_principal="$3" host_id="$4" kind="$5" message
    message="$(awk -F: -v file="$file" -v username="$username" -v numeric="$numeric_principal" -v host="$host_id" -v kind="$kind" '
      function fail(text) { if (!failed) { print kind " " file ": " text; failed = 1 }; exit 1 }
      /^[[:space:]]*$/ || /^[[:space:]]*#/ { next }
      NF != 3 { fail("malformed subordinate-ID record") }
      $1 == "" || $2 !~ /^[0-9]+$/ || $3 !~ /^[0-9]+$/ { fail("malformed subordinate-ID record") }
      {
        start = $2 + 0; count = $3 + 0; end = start + count - 1
        if (start > 4294967295 || count < 1 || count > 4294967295 || end > 4294967295) fail("overflowing subordinate-ID range")
        principal[n] = $1; starts[n] = start; ends[n] = end; counts[n] = count
        if ($1 == username) user_records[++user_count] = n
        if ($1 == numeric) numeric_records[++numeric_count] = n
        n++
      }
      END {
        if (failed) exit 1
        if (user_count && numeric_count) fail("both username and numeric-principal ranges exist")
        if (user_count != 1 && numeric_count != 1) fail("missing or multiple account ranges")
        selected = user_count ? user_records[1] : numeric_records[1]
        if (counts[selected] < 65536) fail("account range is shorter than 65536")
        if (starts[selected] <= host && host <= ends[selected]) fail("account range contains host ID")
        for (i = 0; i < n; i++) {
          if (principal[i] != username && principal[i] != numeric && starts[selected] <= ends[i] && starts[i] <= ends[selected]) fail("account range overlaps foreign allocation")
        }
      }
    ' "$file" 2>&1)" || _docker_fail "$message"
  }

  _docker_verify_rootful() {
    local unit state
    for unit in docker.service docker.socket; do
      state="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
      [ "$state" = masked ] || _docker_fail "$unit is not masked; ask an administrator to mask rootful Docker"
      if systemctl is-active --quiet "$unit"; then
        _docker_fail "$unit remains active; ask an administrator to stop rootful Docker"
      fi
    done
    if [ -e /var/run/docker.sock ] || [ -L /var/run/docker.sock ]; then
      _docker_fail "/var/run/docker.sock exists; ask an administrator to remove the rootful socket"
    fi
  }

  _docker_load_iptables_module() {
    local iptables_command version module=nf_tables candidate
    iptables_command="$(command -v iptables 2>/dev/null || true)"
    if [ -z "$iptables_command" ]; then
      for candidate in /usr/sbin/iptables /sbin/iptables; do
        if [ -x "$candidate" ]; then iptables_command="$candidate"; break; fi
      done
    fi
    [ -n "$iptables_command" ] || {
      _docker_fail "iptables is missing after Docker installation; remediate the Docker packages"; return 1
    }
    version="$("$iptables_command" --version 2>/dev/null)" || {
      _docker_fail "could not determine the iptables backend; remediate iptables"; return 1
    }
    case "$version" in *legacy*) module=ip_tables ;; esac
    sudo modprobe "$module" || {
      _docker_fail "failed to load the $module kernel module required by rootless Docker"; return 1
    }
  }

  _docker_wait_user_manager() {
    local user="$1" uid="$2" runtime="$3" i
    for ((i = 0; i < 30; i++)); do
      if [ -d "$runtime" ] && [ -S "$runtime/bus" ] && systemctl --user show-environment >/dev/null 2>&1; then
        return 0
      fi
      sleep 1
    done
    loginctl user-status "$user" >&2 || true
    sudo systemctl status "user@$uid.service" --no-pager >&2 || true
    _docker_fail "timed out waiting for user systemd manager; log in again or ask an administrator to inspect user@$uid.service"
  }

  _setup_rootless_docker() {
    local incoming_runtime="${XDG_RUNTIME_DIR:-}" arch user uid gid passwd_record passwd_name passwd_uid passwd_gid passwd_home
    local marker_unit="$HOME/.config/systemd/user/docker.service" marker_context="$HOME/.docker/contexts/meta/12b961af5feb3e9d39f93b2cefb9a1a944f18d02cca0cac2f04f5a982240605f/meta.json" marker_state
    local docker_source root_socket_state runtime mode_text mode_value owner endpoint socket_path

    if ! ( . /etc/os-release && [ "$ID" = debian ] && [ "$VERSION_ID" = 13 ] && [ "$VERSION_CODENAME" = trixie ] ); then
      _docker_fail "rootless Docker requires Debian 13 Trixie; remediate the operating system"; return 1
    fi
    arch="$(dpkg --print-architecture)"
    case "$arch" in amd64|arm64) ;; *) _docker_fail "unsupported Debian architecture $arch; use amd64 or arm64"; return 1 ;; esac
    [ "$(ps -p 1 -o comm= 2>/dev/null | tr -d '[:space:]')" = systemd ] || { _docker_fail "PID 1 must be systemd; boot a systemd host"; return 1; }
    [ -d /run/systemd/system ] || { _docker_fail "systemd runtime is unavailable; boot a systemd host"; return 1; }
    case "$(systemctl show --property=SystemState --value)" in running|degraded) ;; *) _docker_fail "system manager is not running; remediate systemd"; return 1 ;; esac
    systemctl is-active --quiet systemd-logind.service || { _docker_fail "systemd-logind is inactive; enable logind"; return 1; }
    [ -r /sys/fs/cgroup/cgroup.controllers ] || { _docker_fail "cgroup v2 is required; enable the unified cgroup hierarchy"; return 1; }

    user="$(id -un)"; uid="$(id -u)"; gid="$(id -g)"
    [[ "$user" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || { _docker_fail "invalid login name; use a regular account"; return 1; }
    [[ "$uid" =~ ^[1-9][0-9]*$ && "$gid" =~ ^[1-9][0-9]*$ ]] || { _docker_fail "UID and GID must be nonzero decimal values"; return 1; }
    passwd_record="$(getent passwd "$user")" || { _docker_fail "missing passwd record for $user"; return 1; }
    IFS=: read -r passwd_name _ passwd_uid passwd_gid _ passwd_home _ <<< "$passwd_record"
    if [ "$passwd_name" != "$user" ] || [ "$passwd_uid" != "$uid" ] || [ "$passwd_gid" != "$gid" ] || [ "$passwd_home" != "$HOME" ]; then
      _docker_fail "passwd record does not match the deployment account"; return 1
    fi
    [ "$(id -u "$user")" = "$uid" ] && [ "$(id -g "$user")" = "$gid" ] || { _docker_fail "account identity lookup mismatch"; return 1; }

    install_package uidmap || return 1
    for tool in newuidmap newgidmap getsubids; do bin_exists "$tool" || { _docker_fail "$tool is missing after uidmap installation; remediate uidmap"; return 1; }; done
    _docker_validate_subids /etc/subuid "$user" "$uid" "$uid" uid || return 1
    _docker_validate_subids /etc/subgid "$user" "$gid" "$gid" gid || return 1

    if [ -e "$marker_unit" ] && [ -e "$marker_context" ]; then marker_state=both
    elif [ -e "$marker_unit" ] || [ -e "$marker_context" ]; then
      _docker_fail "partial rootless Docker state exists; manually repair or remove exactly the user unit or context before rerun"; return 1
    else marker_state=none; fi

    service_mask docker.service docker.socket || return 1
    if [ -e /var/run/docker.sock ] || [ -L /var/run/docker.sock ]; then
      root_socket_state=stale/unknown
      if bin_exists ss && ss -xl 2>/dev/null | grep -F /var/run/docker.sock >/dev/null; then root_socket_state=live; fi
      _docker_fail "rootful Docker socket is $root_socket_state; ask an administrator to stop/remove /var/run/docker.sock"; return 1
    fi
    printf -v docker_source '%s\n' \
      'Types: deb' \
      'URIs: https://download.docker.com/linux/debian' \
      'Suites: trixie' \
      'Components: stable' \
      "Architectures: $arch" \
      'Signed-By: /etc/apt/keyrings/docker.asc'
    add_repo apt-deb822 docker "$docker_source" "https://download.docker.com/linux/debian/gpg" || return 1
    remove_packages docker.io docker-compose docker-doc podman-docker containerd runc || return 1
    update_pkg_index || return 1
    install_packages docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras || return 1
    service_mask docker.service docker.socket || return 1
    _docker_verify_rootful || return 1
    _docker_load_iptables_module || return 1

    sudo loginctl enable-linger "$user" || return 1
    runtime="$(loginctl show-user "$user" --property=RuntimePath --value)"
    [ "$runtime" = "/run/user/$uid" ] || { _docker_fail "unexpected RuntimePath $runtime; remediate logind"; return 1; }
    [ -z "$incoming_runtime" ] || [ "$incoming_runtime" = "$runtime" ] || { _docker_fail "incoming XDG_RUNTIME_DIR conflicts with logind runtime path"; return 1; }
    export XDG_RUNTIME_DIR="$runtime"
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
    export XDG_CONFIG_HOME="$HOME/.config"
    export DOCKER_CONFIG="$HOME/.docker"
    unset DOCKER_HOST DOCKER_CONTEXT
    if ! systemctl is-active --quiet "user@$uid.service"; then sudo systemctl start "user@$uid.service" || return 1; fi
    _docker_wait_user_manager "$user" "$uid" "$runtime" || return 1
    owner="$(stat -c %u "$runtime")"; mode_text="$(stat -c %a "$runtime")"
    [[ "$mode_text" =~ ^[0-7]+$ ]] || { _docker_fail "invalid runtime directory mode"; return 1; }
    mode_value=$((8#$mode_text))
    [ "$owner" = "$uid" ] && [ $((mode_value & 077)) -eq 0 ] || { _docker_fail "runtime directory ownership or permissions are unsafe"; return 1; }
    if [ "$marker_state" = none ]; then
      env -u DOCKER_HOST -u DOCKER_CONTEXT dockerd-rootless-setuptool.sh install || return 1
    fi
    systemctl --user enable --now docker.service || return 1
    env -u DOCKER_HOST -u DOCKER_CONTEXT docker context use rootless || return 1
    endpoint="$(env -u DOCKER_HOST -u DOCKER_CONTEXT docker context inspect rootless --format '{{.Endpoints.docker.Host}}')"
    [ "$endpoint" = "unix:///run/user/$uid/docker.sock" ] || { _docker_fail "rootless context endpoint is not canonical"; return 1; }
    socket_path="/run/user/$uid/docker.sock"
    [ -S "$socket_path" ] && [ "$(stat -c %u "$socket_path")" = "$uid" ] || { _docker_fail "rootless Docker socket is missing or owned by another user"; return 1; }
    env -u DOCKER_HOST -u DOCKER_CONTEXT docker info --format '{{json .SecurityOptions}}' | grep -q rootless || { _docker_fail "Docker security options do not report rootless"; return 1; }
    [ "$(env -u DOCKER_HOST -u DOCKER_CONTEXT docker info --format '{{.CgroupVersion}}')" = 2 ] || { _docker_fail "Docker does not report cgroup v2"; return 1; }
    _docker_verify_rootful
  }

  _setup_rootless_docker
); then
  component_end "docker" 0
else
  _rc=$?; component_end "docker" "$_rc"; exit "$_rc"
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

log "setup complete"
