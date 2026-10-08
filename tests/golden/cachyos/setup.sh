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
deployment_preflight
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
  install_packages git curl git-delta just jq yq fzf ripgrep fd eza bat tree vim htop btop cloc gnupg bash-completion protobuf shelly
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

# --- herdr ---
component_begin "herdr"
if (
  set -e
  _install_herdr() {
    local arch bun_path checksum plugin_json remote_bin
    install_package unzip
    if [ ! -x "$HOME/.bun/bin/bun" ]; then
      BUN_INSTALL="$HOME/.bun" install_script bun "https://bun.com/install"
    fi
    if [ -x "$HOME/.bun/bin/bun" ]; then
      bun_path="$HOME/.bun/bin"
    elif bin_exists bun; then
      bun_path="$(dirname "$(command -v bun)")"
    else
      error "Bun installer completed; bun unavailable"
      return 1
    fi
    case "$(detect_arch)" in
      x86_64) arch=x86_64; checksum=976150a14d490c94b243ea2e1a7eb2dfb67f12e36b182db90936f6728e6aecf4 ;;
      aarch64|arm64) arch=aarch64; checksum=f55610658e1c2e0d2aaef730b4b2ab885f7f8ba00285ab372bfb14f2e3d5b40d ;;
      *) error "unsupported arch for Herdr: $(detect_arch)"; return 1 ;;
    esac
    download_bin_sha256 herdr "https://github.com/herdrdev/herdr/releases/download/v0.8.2/herdr-linux-${arch}" "$checksum" "0.8.2" --version
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
    install_config "$DIR/config/herdr/local.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/local.toml"
    install_config "$DIR/config/herdr/remote.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/remote.toml"
    install -m 0755 "$DIR/config/herdr/herd-local" "$HOME/.local/bin/herd-local"
    install -m 0755 "$DIR/config/herdr/herd-remote" "$HOME/.local/bin/herd-remote"
    plugin_json="$("$remote_bin" plugin list --plugin "herdr.collie" --json)"
    if ! jq -e '
      .result.plugins[]
      | select(
          .plugin_id == "herdr.collie"
          and .source.kind == "github"
          and .source.owner == "AltanS"
          and .source.repo == "collie"
        )
    ' <<<"$plugin_json" >/dev/null; then
      PATH="$bun_path:$PATH" "$remote_bin" plugin install "AltanS/collie" --yes
    fi
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
); then
  component_end "helix" 0
else
  _rc=$?; component_end "helix" "$_rc"; exit "$_rc"
fi

# --- marksman ---
component_begin "marksman"
if (
  set -e
  _install_marksman() {
    local asset checksum
    case "$(detect_arch)" in
      x86_64) asset=marksman-linux-x64; checksum=be5098e8213219269c47fc0d916a66fa31ce0602ec967475c722260aabf26087 ;;
      aarch64|arm64) asset=marksman-linux-arm64; checksum=db8e124527f7f8048e3e6c91821b9c52ef173d92c01e47d221bf1337afd962fb ;;
      *) error "unsupported arch for Marksman: $(detect_arch)"; return 1 ;;
    esac
    download_bin_sha256 marksman "https://github.com/artempyanykh/marksman/releases/download/2026-02-08/${asset}" "$checksum" "2026-02-08" --version
  }
  _install_marksman
); then
  component_end "marksman" 0
else
  _rc=$?; component_end "marksman" "$_rc"; exit "$_rc"
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
    download_bin kubectl "https://dl.k8s.io/release/v1.35.8/bin/linux/${arch}/kubectl" "v1.35.8" version --client
  }
  _install_helm_linux() {
    local arch
    arch="$(_kube_arch)"
    download_tar_bin helm "https://get.helm.sh/helm-v3.21.4-linux-${arch}.tar.gz" "linux-${arch}/helm" "v3.21.4" version --template '{{.Version}}'
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
    download_bin kubie "https://github.com/sbstp/kubie/releases/download/v0.28.0/kubie-linux-${arch}" "0.28.0" --version
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

# --- uv ---
component_begin "uv"
if (
  set -e
  install_script uv https://astral.sh/uv/install.sh
); then
  component_end "uv" 0
else
  _rc=$?; component_end "uv" "$_rc"; exit "$_rc"
fi

# --- python_tools ---
component_begin "python_tools"
if (
  set -e
  install_packages gcc make pkgconf openssl libffi
  uv_bin="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"
  if [ ! -x "$uv_bin" ]; then
    error "python_tools: uv not found"
    exit 1
  fi
  "$uv_bin" tool install python-lsp-server
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
  install_package github-cli
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
  rustup component add rust-analyzer
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
      x86_64) arch=x86_64; checksum=dad2faf6377d2daa4f4fabf459fe7ccfb98a5448f0d4bca8270ca9acb0409bfe ;;
      aarch64|arm64) arch=aarch64; checksum=82df9d765856d0d94d2147cc0912016e4a2bfb96cbe947347b7cc04c7f4431ba ;;
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
    curl -fsSL "https://github.com/tamasfe/taplo/releases/download/0.10.0/taplo-linux-${arch}.gz" | gzip -dc > "$tmp"
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

# --- terraform ---
component_begin "terraform"
if (
  set -e
  install_package terraform
  _install_terragrunt_linux() {
    local arch checksum
    case "$(detect_arch)" in
      x86_64) arch=amd64 ;;
      aarch64|arm64) arch=arm64 ;;
      *) error "unsupported arch for Terragrunt: $(detect_arch)"; return 1 ;;
    esac
    case "$arch" in
      amd64) checksum="513eff2f87e2f5ec84369cc0f9d6c6766b43ca765fec4a3ac3598b933dc3218f" ;;
      arm64) checksum="5cf6006c99b4d05e03eea1375cf8a591ade8b06a40e804b0b73f89f7589347c3" ;;
    esac
    download_bin_sha256 terragrunt \
      "https://github.com/gruntwork-io/terragrunt/releases/download/v0.96.1/terragrunt_linux_${arch}" \
      "$checksum" "v0.96.1" --version
  }
  _install_terragrunt_linux
); then
  component_end "terraform" 0
else
  _rc=$?; component_end "terraform" "$_rc"; exit "$_rc"
fi

# --- zig ---
component_begin "zig"
if (
  set -e
  install_package xz
  _install_zig() (
    local arch checksum zig_dir parent stage archive actual
    case "$(detect_arch)" in
      x86_64) arch=x86_64; checksum=70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00 ;;
      aarch64|arm64) arch=aarch64; checksum=ea4b09bfb22ec6f6c6ceac57ab63efb6b46e17ab08d21f69f3a48b38e1534f17 ;;
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
    curl -fsSL "https://ziglang.org/download/0.16.0/zig-${arch}-linux-0.16.0.tar.xz" -o "$archive"
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

# --- steps ---
component_begin "steps"
if (
  set -e
  uv_bin="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"
  if [ ! -x "$uv_bin" ]; then
    error "steps: uv not found"
    exit 1
  fi
  if ! bin_exists npm; then
    fnm_bin="$HOME/.local/share/fnm/fnm"
    if [ -x "$fnm_bin" ]; then
      eval "$("$fnm_bin" env --shell bash)"
    fi
  fi
  if ! bin_exists npm; then
    error "steps: npm unavailable; node_fnm must run before Steps installation"
    exit 1
  fi
  install_config_dir "$DIR/config/steps" "$HOME/.local/share/steps" "steps"
  (
    cd "$HOME/.local/share/steps"
    npm ci --omit=dev --ignore-scripts --no-audit --no-fund
  )
  "$uv_bin" tool install --reinstall "$HOME/.local/share/steps"
); then
  component_end "steps" 0
else
  _rc=$?; component_end "steps" "$_rc"; exit "$_rc"
fi

# --- pi_agent ---
component_begin "pi_agent"
if (
  set -e
  install_package bubblewrap
  install_npm_global @earendil-works/pi-coding-agent @earendil-works/pi-server @earendil-works/pi-client
  ensure_dir "$HOME/.pi/agent"
  ensure_dir "$HOME/.config/pi/sandbox"
  ensure_dir "$HOME/.local/bin"
  install_config_dir "$DIR/config/pi/agent" "$HOME/.pi/agent" "pi-agent" "settings.json"
  install_json_patch "$DIR/config/managed-settings/pi.json" "$HOME/.pi/agent/settings.json" 0600
  install -m 0755 "$DIR/config/pi/launcher/pi.sh" "$HOME/.local/bin/pi"
  install -m 0755 "$DIR/config/pi/sandbox/pi-sandbox.sh" "$HOME/.local/bin/pi-sandbox"

  install_config_dir "$DIR/config/pi-angelini" "$HOME/repos/pi-angelini"

  pi-unsafe() {
    "$HOME/.local/bin/pi" "$@"
  }
  pi-unsafe update
  pi-unsafe update --extensions

  "$HOME/.local/bin/herdr" integration install pi
); then
  component_end "pi_agent" 0
else
  _rc=$?; component_end "pi_agent" "$_rc"; exit "$_rc"
fi

# --- postgres ---
component_begin "postgres"
if (
  set -e
  install_package postgresql
); then
  component_end "postgres" 0
else
  _rc=$?; component_end "postgres" "$_rc"; exit "$_rc"
fi

# --- go_lang ---
component_begin "go_lang"
if (
  set -e
  install_packages curl git make bison gcc glibc
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
  _install_gcloud_cachyos() (
    local asset_arch checksum root marker parent archive="" stage="" extracted actual
    case "$(detect_arch)" in
      x86_64) asset_arch=amd64; checksum=6b566621ce59a900d520a30d505b9cef1c2bdd72826103175727ac6db1702101 ;;
      aarch64|arm64) asset_arch=aarch64; checksum=c7808b357c1781ed1f0fa0876316ebb901aa86727fb17e2ede229de8b94d95b0 ;;
      *) error "unsupported arch for Google Cloud CLI: $(detect_arch)"; exit 1 ;;
    esac
    root="$HOME/.local/share/google-cloud-sdk"
    marker="$root/.dotgen-archive-sha256"
    parent="${root%/*}"
    if [ -e "$root" ] || [ -L "$root" ]; then
      if [ ! -d "$root" ] || [ -L "$root" ]; then
        error "unsafe Google Cloud CLI destination: $root"
        exit 1
      fi
    fi
    if [ -f "$marker" ] && [ ! -L "$marker" ] && [ "$(cat "$marker")" = "$checksum" ] &&     bin_version_matches "$root/bin/gcloud" "587.0.0" version; then
      exit 0
    fi
    ensure_dir "$parent"
    archive="$(mktemp)"
    stage="$(mktemp -d "$parent/.google-cloud-sdk.XXXXXX")"
    trap 'rm -f -- "$archive"; [ -z "$stage" ] || rm -rf -- "$stage"' EXIT
    curl -fsSL     "https://dl.google.com/dl/cloudsdk/release/downloads/for_packagers/linux/google-cloud-cli_587.0.0.orig_${asset_arch}.tar.gz"     -o "$archive"
    actual="$(sha256_file "$archive")"
    if [ "$actual" != "$checksum" ]; then
      error "Google Cloud CLI archive checksum mismatch"
      exit 1
    fi
    tar -xzf "$archive" -C "$stage"
    extracted="$stage/google-cloud-sdk"
    if ! bin_version_matches "$extracted/bin/gcloud" "587.0.0" version; then
      error "Google Cloud CLI archive version mismatch"
      exit 1
    fi
    printf '%s
  ' "$checksum" > "$extracted/.dotgen-archive-sha256"
    chmod 0644 "$extracted/.dotgen-archive-sha256"
    rm -rf -- "$root"
    mv -- "$extracted" "$root"
  )
  _install_gcloud_cachyos
  remove_packages google-cloud-cli
); then
  component_end "gcloud" 0
else
  _rc=$?; component_end "gcloud" "$_rc"; exit "$_rc"
fi

# --- aws ---
component_begin "aws"
if (
  set -e
  install_package aws-cli-v2
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
  case "$(detect_arch)" in
    x86_64) doppler_arch=amd64; doppler_checksum=1b2f412d984920d665daf233ab6c15b364df9339b5c5b5224d5e8ee4e0a70154 ;;
    aarch64|arm64) doppler_arch=arm64; doppler_checksum=567f051c4c334b79a37ee44c9373671c451dd8a4945ed49288a8f3fd0b73ec89 ;;
    *) error "unsupported arch for Doppler: $(detect_arch)"; exit 1 ;;
  esac
  download_tar_bin_sha256 doppler   "https://github.com/DopplerHQ/cli/releases/download/3.76.5/doppler_3.76.5_linux_${doppler_arch}.tar.gz"   "$doppler_checksum" doppler "v3.76.5" --version
  unset doppler_arch doppler_checksum
  remove_packages doppler-cli-bin
); then
  component_end "doppler" 0
else
  _rc=$?; component_end "doppler" "$_rc"; exit "$_rc"
fi

# --- fonts ---
component_begin "fonts"
if (
  set -e
  install_packages fontconfig ttf-ubuntu-font-family ttf-ubuntu-mono-nerd
); then
  component_end "fonts" 0
else
  _rc=$?; component_end "fonts" "$_rc"; exit "$_rc"
fi

# --- ghostty ---
component_begin "ghostty"
if (
  set -e
  install_package ghostty
  if ! bin_exists ghostty; then error "Ghostty package installed without ghostty CLI"; exit 1; fi
  install_config "$DIR/config/ghostty/config" "${XDG_CONFIG_HOME:-$HOME/.config}/ghostty/config"
); then
  component_end "ghostty" 0
else
  _rc=$?; component_end "ghostty" "$_rc"; exit "$_rc"
fi

# --- zed ---
component_begin "zed"
if (
  set -e
  install_package zed
  if ! bin_exists zeditor; then error "Zed package installed without zeditor CLI"; exit 1; fi
  install_config "$DIR/config/zed/settings.json" "${XDG_CONFIG_HOME:-$HOME/.config}/zed/settings.json"
  install_config "$DIR/config/zed/keymap.json" "${XDG_CONFIG_HOME:-$HOME/.config}/zed/keymap.json"
); then
  component_end "zed" 0
else
  _rc=$?; component_end "zed" "$_rc"; exit "$_rc"
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

  _docker_check_rootful_preflight() {
    local unit root_socket_state
    for unit in docker.service docker.socket; do
      if systemctl is-active --quiet "$unit"; then
        _docker_fail "$unit is active; stop rootful Docker before deployment"
        return 1
      fi
    done
    if [ -e /var/run/docker.sock ] || [ -L /var/run/docker.sock ]; then
      root_socket_state=stale/unknown
      if bin_exists ss && ss -xl 2>/dev/null | grep -F /var/run/docker.sock >/dev/null; then root_socket_state=live; fi
      _docker_fail "rootful Docker socket is $root_socket_state; ask an administrator to stop/remove /var/run/docker.sock"
    fi
  }

  _docker_ensure_iptables_module() {
    local module=nf_tables version
    version="$(iptables --version 2>/dev/null)" || { _docker_fail "could not determine the iptables backend; remediate iptables"; return 1; }
    case "$version" in *legacy*) module=ip_tables ;; esac
    if grep -qw "$module" /proc/modules 2>/dev/null || grep -qw "$module" "/lib/modules/$(uname -r)/modules.builtin" 2>/dev/null; then
      return 0
    fi
    sudo modprobe "$module" || { _docker_fail "failed to load the $module kernel module required by rootless Docker"; return 1; }
  }

  _docker_user_manager_diagnostics() {
    local user="$1" uid="$2"
    loginctl user-status "$user" >&2 || true
    sudo systemctl status "user@$uid.service" --no-pager >&2 || true
  }

  _setup_rootless_docker_cachyos() {
    local incoming_runtime="${XDG_RUNTIME_DIR:-}" arch user uid gid passwd_record passwd_name passwd_uid passwd_gid passwd_home
    local runtime runtime_owner mode_text mode_value marker_unit="$HOME/.config/systemd/user/docker.service.d/10-dotgen-socket-mode.conf"
    local marker_context="$HOME/.docker/contexts/meta/12b961af5feb3e9d39f93b2cefb9a1a944f18d02cca0cac2f04f5a982240605f/meta.json"
    local service_unit="$HOME/.config/systemd/user/docker.service"
    local unit_state marker_state endpoint socket_path socket_owner socket_mode driver tool

    if ! ( . /etc/os-release && [ "$ID" = cachyos ] && [[ " ${ID_LIKE:-} " = *" arch "* ]] ); then
      _docker_fail "rootless Docker requires CachyOS with ID_LIKE=arch; remediate the operating system"; return 1
    fi
    arch="$(uname -m)"
    [ "$arch" = x86_64 ] || { _docker_fail "unsupported CachyOS architecture $arch; use x86_64"; return 1; }
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

    runtime="$(loginctl show-user "$user" --property=RuntimePath --value)"
    [ "$runtime" = "/run/user/$uid" ] || { _docker_fail "unexpected RuntimePath $runtime; remediate logind"; return 1; }
    [ -z "$incoming_runtime" ] || [ "$incoming_runtime" = "$runtime" ] || { _docker_fail "incoming XDG_RUNTIME_DIR conflicts with logind runtime path"; return 1; }
    [ -d "$runtime" ] && [ ! -L "$runtime" ] || { _docker_fail "canonical runtime directory is missing or unsafe"; return 1; }
    runtime_owner="$(stat -c %u "$runtime")"; mode_text="$(stat -c %a "$runtime")"
    [[ "$mode_text" =~ ^[0-7]+$ ]] || { _docker_fail "invalid runtime directory mode"; return 1; }
    mode_value=$((8#$mode_text))
    [ "$runtime_owner" = "$uid" ] && [ $((mode_value & 077)) -eq 0 ] || { _docker_fail "runtime directory ownership or permissions are unsafe"; return 1; }
    [ -S "$runtime/bus" ] && systemctl --user show-environment >/dev/null 2>&1 || {
      _docker_user_manager_diagnostics "$user" "$uid"
      _docker_fail "user systemd manager is unreachable; log in again or inspect user@$uid.service"; return 1
    }

    _docker_validate_subids /etc/subuid "$user" "$uid" "$uid" uid || return 1
    _docker_validate_subids /etc/subgid "$user" "$gid" "$gid" gid || return 1

    unit_state="$(systemctl --user is-enabled docker.service 2>/dev/null || true)"
    if [ -e "$marker_unit" ] && [ -e "$marker_context" ] && [ "$unit_state" = enabled ]; then marker_state=both
    elif [ -e "$marker_unit" ] || [ -e "$marker_context" ] || [ "$unit_state" = enabled ]; then
      _docker_fail "partial rootless Docker state exists; manually reconcile the user service marker, enablement, and rootless context"; return 1
    else marker_state=none; fi
    if [ -e "$marker_unit" ]; then
      if [ -L "$marker_unit" ] || [ ! -f "$marker_unit" ] || [ "$(stat -c %u "$marker_unit")" != "$uid" ] || [ "$(stat -c %a "$marker_unit")" != 600 ] ||
        [ "$(cat "$marker_unit")" != $'[Service]\nExecStartPost=/usr/bin/chmod 0600 %t/docker.sock' ]; then
        _docker_fail "rootless Docker service marker is unsafe or unmanaged; remediate it manually"; return 1
      fi
    fi
    if [ -e "$marker_context" ] && { [ -L "$marker_context" ] || [ ! -f "$marker_context" ]; }; then
      _docker_fail "rootless Docker context marker is unsafe; remediate it manually"; return 1
    fi
    socket_path="$runtime/docker.sock"
    if [ -e "$socket_path" ] || [ -L "$socket_path" ]; then
      [ "$marker_state" = both ] || { _docker_fail "unexpected rootless Docker socket exists without complete managed state"; return 1; }
      [ -S "$socket_path" ] && [ ! -L "$socket_path" ] || { _docker_fail "rootless Docker socket path is not a socket"; return 1; }
      [ "$(stat -c %u "$socket_path")" = "$uid" ] || { _docker_fail "rootless Docker socket is owned by another user"; return 1; }
    fi
    _docker_check_rootful_preflight || return 1

    service_mask docker.service docker.socket || return 1
    install_packages docker docker-compose docker-buildx rootlesskit slirp4netns fuse-overlayfs shadow iptables || return 1
    remove_packages docker-rootless-extras || return 1
    download_script_sha256 dockerd-rootless.sh \
      "https://raw.githubusercontent.com/moby/moby/docker-v29.8.2/contrib/dockerd-rootless.sh" \
      "200203633806081a401e60aefdf68a8fa73fc7dc80aa854c52a69d47710a3488" || return 1
    if [ -L "$service_unit" ] || { [ -e "$service_unit" ] && [ ! -f "$service_unit" ]; }; then
      _docker_fail "rootless Docker user service destination is unsafe"; return 1
    fi
    install -d -m 0700 "$HOME/.config/systemd/user" || return 1
    install -m 0600 "$DIR/config/docker/docker.service" "$service_unit" || return 1
    service_mask docker.service docker.socket || return 1
    _docker_verify_rootful || return 1
    [ -x "$HOME/bin/dockerd-rootless.sh" ] || {
      _docker_fail "$HOME/bin/dockerd-rootless.sh is missing after Docker installation; rerun the deployment to restore it"; return 1
    }
    for tool in docker dockerd rootlesskit slirp4netns fuse-overlayfs newuidmap newgidmap getsubids iptables; do
      bin_exists "$tool" || { _docker_fail "$tool is missing after Docker installation; remediate the selected packages"; return 1; }
    done
    _docker_ensure_iptables_module || return 1

    sudo loginctl enable-linger "$user" || return 1
    export XDG_RUNTIME_DIR="$runtime"
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus"
    export XDG_CONFIG_HOME="$HOME/.config"
    export DOCKER_CONFIG="$HOME/.docker"
    unset DOCKER_HOST DOCKER_CONTEXT

    if [ "$marker_state" = none ]; then
      install -d -m 0700 "$HOME/.config/systemd/user/docker.service.d" || return 1
      printf '%s\n' '[Service]' 'ExecStartPost=/usr/bin/chmod 0600 %t/docker.sock' > "$marker_unit" || return 1
      chmod 0600 "$marker_unit" || return 1
      systemctl --user daemon-reload || return 1
      env -u DOCKER_HOST -u DOCKER_CONTEXT docker --context=default context create rootless \
        --docker "host=unix://$runtime/docker.sock" --description "Rootless mode" >/dev/null || return 1
    else
      systemctl --user daemon-reload || return 1
    fi
    systemctl --user enable --now docker.service || return 1
    env -u DOCKER_HOST -u DOCKER_CONTEXT docker --context=default context use rootless >/dev/null || return 1
    [ "$(env -u DOCKER_HOST -u DOCKER_CONTEXT docker context show)" = rootless ] || { _docker_fail "Docker did not select the rootless context"; return 1; }
    endpoint="$(env -u DOCKER_HOST -u DOCKER_CONTEXT docker context inspect rootless --format '{{.Endpoints.docker.Host}}')"
    [ "$endpoint" = "unix://$runtime/docker.sock" ] || { _docker_fail "rootless context endpoint is not canonical"; return 1; }
    [ -S "$socket_path" ] && [ ! -L "$socket_path" ] || { _docker_fail "rootless Docker socket is missing or unsafe"; return 1; }
    socket_owner="$(stat -c %u "$socket_path")"; socket_mode="$(stat -c %a "$socket_path")"
    [ "$socket_owner" = "$uid" ] && [ "$socket_mode" = 600 ] || { _docker_fail "rootless Docker socket must be deployment-user-owned with mode 0600"; return 1; }
    systemctl --user is-active --quiet docker.service || { _docker_fail "rootless docker.service is inactive"; return 1; }
    env -u DOCKER_HOST -u DOCKER_CONTEXT docker info --format '{{json .SecurityOptions}}' | grep -q rootless || { _docker_fail "Docker security options do not report rootless"; return 1; }
    [ "$(env -u DOCKER_HOST -u DOCKER_CONTEXT docker info --format '{{.CgroupVersion}}')" = 2 ] || { _docker_fail "Docker does not report cgroup v2"; return 1; }
    driver="$(env -u DOCKER_HOST -u DOCKER_CONTEXT docker info --format '{{.Driver}}')"
    case "$driver" in overlayfs|overlay2|fuse-overlayfs) ;; *) _docker_fail "unsupported rootless Docker storage driver $driver"; return 1 ;; esac
    env -u DOCKER_HOST -u DOCKER_CONTEXT docker compose version >/dev/null || { _docker_fail "Docker Compose plugin verification failed"; return 1; }
    env -u DOCKER_HOST -u DOCKER_CONTEXT docker buildx version >/dev/null || { _docker_fail "Docker Buildx plugin verification failed"; return 1; }
    _docker_verify_rootful
  }

  _setup_rootless_docker_cachyos
); then
  component_end "docker" 0
else
  _rc=$?; component_end "docker" "$_rc"; exit "$_rc"
fi

# --- zed_host_bridge ---
component_begin "zed_host_bridge"
if (
  set -e
  \
  load_secrets
  zed_bridge_ssh_host=${ZED_HOST_BRIDGE_SSH_HOST:-}
  if [ "${#zed_bridge_ssh_host}" -gt 255 ] || ! [[ "$zed_bridge_ssh_host" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
    error "ZED_HOST_BRIDGE_SSH_HOST must be an exact SSH alias containing only ASCII letters, digits, dots, and hyphens"
    exit 1
  fi
  \
  _zed_bridge_assert_dir() {
    local directory=$1 parent
    parent="$(dirname "$directory")"
    if [ -L "$directory" ] || { [ -e "$directory" ] && [ ! -d "$directory" ]; }; then
      error "unsafe Zed host bridge directory: $directory"
      return 1
    fi
    if [ ! -e "$directory" ]; then
      if [ ! -d "$parent" ] || [ -L "$parent" ]; then
        error "unsafe Zed host bridge parent directory: $parent"
        return 1
      fi
      mkdir -- "$directory"
    fi
    if [ ! -O "$directory" ]; then
      error "Zed host bridge directory is not owned by the current user: $directory"
      return 1
    fi
  }

  _zed_bridge_safe_dir() {
    local directory=$1 mode=$2
    _zed_bridge_assert_dir "$directory"
    chmod "$mode" "$directory"
  }

  _zed_bridge_install_file() {
    local source=$1 destination=$2 mode=$3 parent staging
    parent="$(dirname "$destination")"
    _zed_bridge_assert_dir "$parent"
    if [ -L "$destination" ] || { [ -e "$destination" ] && { [ ! -f "$destination" ] || [ ! -O "$destination" ]; }; }; then
      error "unsafe Zed host bridge destination: $destination"
      return 1
    fi
    staging="$(mktemp "$parent/.dotgen-zed-host-bridge.XXXXXX")"
    if ! install -m "$mode" "$source" "$staging"; then
      rm -f -- "$staging"
      return 1
    fi
    if [ -L "$destination" ] || { [ -e "$destination" ] && { [ ! -f "$destination" ] || [ ! -O "$destination" ]; }; }; then
      rm -f -- "$staging"
      error "unsafe Zed host bridge destination: $destination"
      return 1
    fi
    mv -f -- "$staging" "$destination"
  }

  _zed_bridge_assert_dir "$HOME"
  _zed_bridge_assert_dir "$HOME/.local"
  _zed_bridge_assert_dir "$HOME/.local/libexec"
  _zed_bridge_safe_dir "$HOME/.local/libexec/dotgen" 0700
  _zed_bridge_install_file "$DIR/config/zed-host-bridge/bridge.mjs" "$HOME/.local/libexec/dotgen/zed-host-bridge.mjs" 0644
  \
  _zed_bridge_install_file "$DIR/config/zed-host-bridge/serve-linux" "$HOME/.local/libexec/dotgen/zed-host-bridge-serve-linux" 0755
  config_root="$(printenv XDG_CONFIG_HOME 2>/dev/null || true)"
  cache_root="$(printenv XDG_CACHE_HOME 2>/dev/null || true)"
  config_root="${config_root:-$HOME/.config}"
  cache_root="${cache_root:-$HOME/.cache}"
  _zed_bridge_assert_dir "$config_root"
  _zed_bridge_safe_dir "$config_root/dotgen" 0700
  receiver_config="$config_root/dotgen/zed-host-bridge.json"
  if [ -L "$receiver_config" ] || { [ -e "$receiver_config" ] && { [ ! -f "$receiver_config" ] || [ ! -O "$receiver_config" ]; }; }; then
    error "unsafe Zed host bridge destination: $receiver_config"
    exit 1
  fi
  install_config_template "$DIR/config/zed-host-bridge/config.json.template" "$receiver_config" 'ZED_HOST_BRIDGE_SSH_HOST' 0600

  _zed_bridge_assert_dir "$cache_root"
  _zed_bridge_safe_dir "$cache_root/dotgen" 0700
  bridge_socket="$cache_root/dotgen/zed-host-bridge.sock"
  systemd_root="$config_root/systemd"
  unit_dir="$systemd_root/user"
  _zed_bridge_assert_dir "$systemd_root"
  _zed_bridge_assert_dir "$unit_dir"
  unit_name=dev.dotgen.zed-host-bridge.service
  unit_path="$unit_dir/$unit_name"
  _zed_bridge_install_file "$DIR/config/zed-host-bridge/$unit_name" "$unit_path" 0644
  \
  _zed_bridge_safe_dir "$HOME/.ssh" 0700
  _zed_bridge_safe_dir "$HOME/.ssh/config.d" 0700
  ssh_include="$HOME/.ssh/config.d/dotgen-zed-host-bridge.conf"
  if [ -L "$ssh_include" ] || { [ -e "$ssh_include" ] && { [ ! -f "$ssh_include" ] || [ ! -O "$ssh_include" ]; }; }; then
    error "unsafe Zed host bridge SSH include destination: $ssh_include"
    exit 1
  fi
  install_config_template "$DIR/config/zed-host-bridge/ssh-linux.conf.template" "$ssh_include" 'ZED_HOST_BRIDGE_SSH_HOST' 0600
  chmod 0600 "$ssh_include"

  ssh_main="$HOME/.ssh/config"
  managed_include='Include ~/.ssh/config.d/dotgen-zed-host-bridge.conf'
  if [ -L "$ssh_main" ] || { [ -e "$ssh_main" ] && { [ ! -f "$ssh_main" ] || [ ! -O "$ssh_main" ]; }; }; then
    error "unsafe SSH config destination: $ssh_main"
    exit 1
  fi
  ssh_main_staging="$(mktemp "$HOME/.ssh/.dotgen-ssh-config.XXXXXX")"
  managed_node="$HOME/.local/share/fnm/aliases/default/bin/node"
  if [ ! -x "$managed_node" ]; then
    rm -f -- "$ssh_main_staging"
    error "managed Node runtime is missing: $managed_node"
    exit 1
  fi
  "$managed_node" -e '
  const fs = require("node:fs");
  const [src, dst, line] = process.argv.slice(1);
  const data = fs.existsSync(src) ? fs.readFileSync(src) : Buffer.alloc(0);
  const target = Buffer.from(line);
  const kept = [];
  let start = 0;
  for (let i = 0; i < data.length; i += 1) {
    if (data[i] === 10) {
      const body = data.subarray(start, i);
      if (!(body.length === target.length && body.equals(target))) kept.push(data.subarray(start, i + 1));
      start = i + 1;
    }
  }
  if (start < data.length) {
    const body = data.subarray(start);
    if (!(body.length === target.length && body.equals(target))) kept.push(body);
  }
  fs.writeFileSync(dst, Buffer.concat([target, Buffer.from("\n"), ...kept]), { mode: 0o600 });
  ' "$ssh_main" "$ssh_main_staging" "$managed_include"
  chmod 0600 "$ssh_main_staging"
  if [ -L "$ssh_main" ] || { [ -e "$ssh_main" ] && { [ ! -f "$ssh_main" ] || [ ! -O "$ssh_main" ]; }; }; then
    rm -f -- "$ssh_main_staging"
    error "unsafe SSH config destination: $ssh_main"
    exit 1
  fi
  mv -f -- "$ssh_main_staging" "$ssh_main"

  ssh_effective="$(ssh -G "$zed_bridge_ssh_host" 2>/dev/null)" || {
    error "invalid SSH configuration for Zed host bridge alias: $zed_bridge_ssh_host"
    exit 1
  }
  grep -Fqx 'exitonforwardfailure yes' <<< "$ssh_effective" || { error "Zed host bridge ExitOnForwardFailure setting is not effective"; exit 1; }
  ssh_remote_user="$(awk '$1 == "user" { print $2; exit }' <<< "$ssh_effective")"
  if [ -z "$ssh_remote_user" ]; then
    error "Zed host bridge SSH user is not effective"
    exit 1
  fi
  expected_forward="remoteforward /home/$ssh_remote_user/.cache/dotgen/zed-host-bridge.sock $HOME/.cache/dotgen/zed-host-bridge.sock"
  grep -Fqx "$expected_forward" <<< "$ssh_effective" || {
    error "Zed host bridge RemoteForward setting is not effective"
    exit 1
  }


  _zed_bridge_service_failure() {
    error "$1"
    systemctl --user status "$unit_name" --no-pager >&2 || true
    journalctl --user-unit="$unit_name" -n 50 --no-pager >&2 || true
  }

  if [ -e "$bridge_socket" ] || [ -L "$bridge_socket" ]; then
    if [ -L "$bridge_socket" ] || [ ! -S "$bridge_socket" ]; then
      error "unsafe Zed host bridge socket collision: $bridge_socket"
      exit 1
    fi
    if [ ! -O "$bridge_socket" ]; then
      error "Zed host bridge socket is not owned by the current user: $bridge_socket"
      exit 1
    fi
    if [ "$(stat -c '%a' "$bridge_socket")" != 600 ]; then
      error "Zed host bridge socket does not have mode 0600: $bridge_socket"
      exit 1
    fi
    if systemctl --user is-active --quiet "$unit_name"; then
      log "preserving live Zed host bridge socket until service restart"
    else
      log "leaving safe stale Zed host bridge socket for receiver replacement"
    fi
  fi

  if ! systemctl --user daemon-reload; then
    _zed_bridge_service_failure "failed to reload the systemd user manager"
    exit 1
  fi
  if ! systemctl --user enable "$unit_name"; then
    _zed_bridge_service_failure "failed to enable the Zed host bridge user service"
    exit 1
  fi

  graphical_import=()
  _zed_bridge_env_nonempty() {
    [ -n "$(printenv "$1" 2>/dev/null || true)" ]
  }
  if { _zed_bridge_env_nonempty WAYLAND_DISPLAY || _zed_bridge_env_nonempty DISPLAY; } && _zed_bridge_env_nonempty DBUS_SESSION_BUS_ADDRESS; then
    for variable in WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP DBUS_SESSION_BUS_ADDRESS; do
      if [ -n "${!variable:-}" ]; then
        graphical_import+=("$variable")
      fi
    done
    if ! systemctl --user import-environment "${graphical_import[@]}"; then
      _zed_bridge_service_failure "failed to import the graphical session environment"
      exit 1
    fi
  fi
  manager_environment="$(systemctl --user show-environment)" || {
    _zed_bridge_service_failure "failed to inspect the systemd user-manager environment"
    exit 1
  }
  if grep -Eq '^(WAYLAND_DISPLAY|DISPLAY)=.+' <<< "$manager_environment" && grep -Eq '^DBUS_SESSION_BUS_ADDRESS=.+' <<< "$manager_environment"; then
    if ! systemctl --user restart "$unit_name" || ! systemctl --user is-active --quiet "$unit_name"; then
      _zed_bridge_service_failure "failed to start the Zed host bridge user service"
      exit 1
    fi
    socket_ready=0
    for ((socket_attempt=0; socket_attempt<50; socket_attempt++)); do
      if [ -S "$bridge_socket" ]; then
        socket_ready=1
        break
      fi
      sleep 0.2
    done
    if [ "$socket_ready" -ne 1 ]; then
      _zed_bridge_service_failure "Zed host bridge user service started without creating its socket"
      exit 1
    fi
    if [ ! -O "$bridge_socket" ] || [ "$(stat -c '%a' "$bridge_socket")" != 600 ]; then
      _zed_bridge_service_failure "Zed host bridge user service created an unsafe socket"
      exit 1
    fi
  else
    log "Zed host bridge user service installed; activation deferred until a graphical login"
  fi
); then
  component_end "zed_host_bridge" 0
else
  _rc=$?; component_end "zed_host_bridge" "$_rc"; exit "$_rc"
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
