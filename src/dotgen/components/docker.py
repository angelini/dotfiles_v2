from dataclasses import dataclass
from pathlib import Path

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS, EnvironmentRole

_KEY_URL = "https://download.docker.com/linux/debian/gpg"
_ROOTLESS_CONTEXT_META = "$HOME/.docker/contexts/meta/12b961af5feb3e9d39f93b2cefb9a1a944f18d02cca0cac2f04f5a982240605f/meta.json"
_ROOTLESS_VERSION = "29.8.2"
_ROOTLESS_SCRIPT_URL = f"https://raw.githubusercontent.com/moby/moby/docker-v{_ROOTLESS_VERSION}/contrib/dockerd-rootless.sh"
_ROOTLESS_SCRIPT_SHA256 = "200203633806081a401e60aefdf68a8fa73fc7dc80aa854c52a69d47710a3488"
_RESOURCE_ROOT = Path(__file__).resolve().parents[1] / "resources" / "docker"
_ROOTLESS_SERVICE = (_RESOURCE_ROOT / "docker.service").read_text()

_DEBIAN_SETUP_TEMPLATE = r"""_docker_fail() {
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
  local marker_unit="$HOME/.config/systemd/user/docker.service" marker_context="__ROOTLESS_CONTEXT_META__" marker_state
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
  add_repo apt-deb822 docker "$docker_source" "__DOCKER_KEY_URL__" || return 1
  remove_packages docker.io docker-compose docker-doc podman-docker containerd runc || return 1
  update_pkg_index || return 1
  install_packages docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras || return 1
  install_package kmod || return 1
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
"""
_DEBIAN_SETUP = _DEBIAN_SETUP_TEMPLATE.replace("__DOCKER_KEY_URL__", _KEY_URL).replace("__ROOTLESS_CONTEXT_META__", _ROOTLESS_CONTEXT_META)

_CACHYOS_SETUP_TEMPLATE = r"""_docker_fail() {
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
    "__ROOTLESS_SCRIPT_URL__" \
    "__ROOTLESS_SCRIPT_SHA256__" || return 1
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
"""
_CACHYOS_SETUP = _CACHYOS_SETUP_TEMPLATE.replace("__ROOTLESS_SCRIPT_URL__", _ROOTLESS_SCRIPT_URL).replace(
    "__ROOTLESS_SCRIPT_SHA256__", _ROOTLESS_SCRIPT_SHA256
)


def _setup_for(env: Environment) -> str:
    if env.os is OS.DEBIAN and env.role is EnvironmentRole.SERVER:
        return _DEBIAN_SETUP
    if env.os is OS.CACHYOS and env.role is EnvironmentRole.WORKSTATION:
        return _CACHYOS_SETUP
    raise ValueError(f"Docker is unsupported for {env.os.value}/{env.role.value}")


@dataclass(frozen=True)
class Docker:
    name: str = "docker"

    def applies_to(self, env: Environment) -> bool:
        return (env.os is OS.DEBIAN and env.role is EnvironmentRole.SERVER) or (env.os is OS.CACHYOS and env.role is EnvironmentRole.WORKSTATION)

    def render(self, env: Environment) -> Fragment:
        configs = (ConfigFile("docker/docker.service", _ROOTLESS_SERVICE),) if env.os is OS.CACHYOS else ()
        return Fragment(setup=_setup_for(env), configs=configs)
