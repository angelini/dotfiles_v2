from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment

_KEY_URL = "https://download.docker.com/linux/debian/gpg"
_ROOTLESS_CONTEXT_META = "$HOME/.docker/contexts/meta/12b961af5feb3e9d39f93b2cefb9a1a944f18d02cca0cac2f04f5a982240605f/meta.json"

_SETUP_TEMPLATE = r"""_docker_fail() {
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
  add_repo apt-deb822 docker "$docker_source" "__DOCKER_KEY_URL__" || return 1
  remove_packages docker.io docker-compose docker-doc podman-docker containerd runc || return 1
  update_pkg_index || return 1
  install_packages docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras || return 1
  [ "$DOTGEN_MODE" = diff ] && return 0
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
_SETUP = _SETUP_TEMPLATE.replace("__DOCKER_KEY_URL__", _KEY_URL).replace("__ROOTLESS_CONTEXT_META__", _ROOTLESS_CONTEXT_META)


@dataclass(frozen=True)
class Docker:
    name: str = "docker"

    def applies_to(self, env: Environment) -> bool:
        return env.name == "debian"

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP)
