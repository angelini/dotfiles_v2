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
    if [ "$DOTGEN_MODE" = deploy ]; then
      for tool in newuidmap newgidmap getsubids; do bin_exists "$tool" || { _docker_fail "$tool is missing after uidmap installation; remediate uidmap"; return 1; }; done
    fi
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
    [ "$DOTGEN_MODE" = diff ] && return 0
    service_mask docker.service docker.socket || return 1
    _docker_verify_rootful || return 1

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

if [ "$DOTGEN_MODE" = deploy ]; then
  log "setup complete"
fi
