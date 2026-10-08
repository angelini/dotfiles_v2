from dataclasses import dataclass
from pathlib import Path

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS, EnvironmentRole

_RESOURCE_ROOT = Path(__file__).resolve().parents[1] / "resources" / "zed_host_bridge"


def _resource_text(name: str) -> str:
    return (_RESOURCE_ROOT / name).read_text()


_BRIDGE = _resource_text("bridge.mjs")
_ZED_LAUNCHER = _resource_text("zed")
_MACOS_SERVER_LAUNCHER = _resource_text("serve")
_LINUX_SERVER_LAUNCHER = _resource_text("serve-linux")
_PLIST = _resource_text("dev.dotgen.zed-host-bridge.plist")
_SYSTEMD_UNIT = _resource_text("dev.dotgen.zed-host-bridge.service")
_MACOS_SSH_CONFIG = _resource_text("ssh.conf.template")
_LINUX_SSH_CONFIG = _resource_text("ssh-linux.conf.template")
_SSHD_CONFIG = _resource_text("sshd.conf")
_RECEIVER_CONFIG = _resource_text("config.json.template")

_COMMON_SETUP = r"""\
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
"""

_DEBIAN_SETUP = (
    _COMMON_SETUP
    + r"""\
_zed_bridge_assert_dir "$HOME/bin"
_zed_bridge_install_file "$DIR/config/zed-host-bridge/zed" "$HOME/bin/zed" 0755
_zed_bridge_assert_dir "$HOME/.cache"
_zed_bridge_safe_dir "$HOME/.cache/dotgen" 0700

sshd_config_dir=/etc/ssh/sshd_config.d
sshd_config="$sshd_config_dir/00-dotgen-zed-host-bridge.conf"
sshd_backup=
sshd_had_config=0
if sudo test -L "$sshd_config" || { sudo test -e "$sshd_config" && ! sudo test -f "$sshd_config"; }; then
  error "unsafe Zed host bridge sshd destination: $sshd_config"
  exit 1
fi
if sudo test -f "$sshd_config"; then
  sshd_backup="$(mktemp)"
  sudo cp -- "$sshd_config" "$sshd_backup"
  sshd_had_config=1
fi
sudo install -d -m 0755 "$sshd_config_dir"
if ! sudo install -m 0644 "$DIR/config/zed-host-bridge/sshd.conf" "$sshd_config" || ! sudo sshd -t || ! sudo systemctl reload ssh; then
  if [ "$sshd_had_config" -eq 1 ]; then
    sudo cp -- "$sshd_backup" "$sshd_config"
  else
    sudo rm -f -- "$sshd_config"
  fi
  if sudo sshd -t; then
    sudo systemctl reload ssh || true
  fi
  [ -z "$sshd_backup" ] || sudo rm -f -- "$sshd_backup"
  error "failed to install Zed host bridge sshd configuration"
  exit 1
fi
[ -z "$sshd_backup" ] || sudo rm -f -- "$sshd_backup"
"""
)

_RECEIVER_PREFIX = (
    r"""\
load_secrets
zed_bridge_ssh_host=${ZED_HOST_BRIDGE_SSH_HOST:-}
if [ "${#zed_bridge_ssh_host}" -gt 255 ] || ! [[ "$zed_bridge_ssh_host" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  error "ZED_HOST_BRIDGE_SSH_HOST must be an exact SSH alias containing only ASCII letters, digits, dots, and hyphens"
  exit 1
fi
"""
    + _COMMON_SETUP
)

_SSH_SETUP = r"""\
_zed_bridge_safe_dir "$HOME/.ssh" 0700
_zed_bridge_safe_dir "$HOME/.ssh/config.d" 0700
ssh_include="$HOME/.ssh/config.d/dotgen-zed-host-bridge.conf"
if [ -L "$ssh_include" ] || { [ -e "$ssh_include" ] && { [ ! -f "$ssh_include" ] || [ ! -O "$ssh_include" ]; }; }; then
  error "unsafe Zed host bridge SSH include destination: $ssh_include"
  exit 1
fi
install_config_template "$DIR/config/zed-host-bridge/SSH_TEMPLATE" "$ssh_include" 'ZED_HOST_BRIDGE_SSH_HOST' 0600
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
SSH_FORWARD_CHECK
"""

_MACOS_SETUP = (
    _RECEIVER_PREFIX
    + r"""\
_zed_bridge_install_file "$DIR/config/zed-host-bridge/serve" "$HOME/.local/libexec/dotgen/zed-host-bridge-serve" 0755
_zed_bridge_assert_dir "${XDG_CONFIG_HOME:-$HOME/.config}"
_zed_bridge_safe_dir "${XDG_CONFIG_HOME:-$HOME/.config}/dotgen" 0700
receiver_config="${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/zed-host-bridge.json"
if [ -L "$receiver_config" ] || { [ -e "$receiver_config" ] && { [ ! -f "$receiver_config" ] || [ ! -O "$receiver_config" ]; }; }; then
  error "unsafe Zed host bridge destination: $receiver_config"
  exit 1
fi
install_config_template "$DIR/config/zed-host-bridge/config.json.template" "$receiver_config" 'ZED_HOST_BRIDGE_SSH_HOST' 0600

_zed_bridge_assert_dir "$HOME/Library"
_zed_bridge_assert_dir "$HOME/Library/Caches"
_zed_bridge_assert_dir "$HOME/Library/Logs"
_zed_bridge_safe_dir "$HOME/Library/Caches/dotgen" 0700
_zed_bridge_assert_dir "$HOME/Library/LaunchAgents"
launch_agent="$HOME/Library/LaunchAgents/dev.dotgen.zed-host-bridge.plist"
_zed_bridge_install_file "$DIR/config/zed-host-bridge/dev.dotgen.zed-host-bridge.plist" "$launch_agent" 0600
"""
    + _SSH_SETUP.replace("SSH_TEMPLATE", "ssh.conf.template").replace(
        "SSH_FORWARD_CHECK",
        r"""grep -E '^remoteforward /home/[^/]+/\.cache/dotgen/zed-host-bridge\.sock .*/Library/Caches/dotgen/zed-host-bridge\.sock$' <<< "$ssh_effective" >/dev/null || {
  error "Zed host bridge RemoteForward setting is not effective"
  exit 1
}""",
    )
    + r"""

launch_domain="gui/$(id -u)"
launch_label="$launch_domain/dev.dotgen.zed-host-bridge"
bridge_log="$HOME/Library/Logs/dotgen-zed-host-bridge.log"
_zed_bridge_launch_failure() {
  error "$1"
  plutil -lint "$launch_agent" >&2 || true
  launchctl print "$launch_label" >&2 || true
  if [ -f "$bridge_log" ]; then
    printf '%s\n' "--- $bridge_log (last 50 lines) ---" >&2
    tail -n 50 "$bridge_log" >&2 || true
  else
    printf '%s\n' "Zed host bridge log does not exist yet: $bridge_log" >&2
  fi
}
if launchctl print "$launch_domain" >/dev/null 2>&1; then
  if launchctl print "$launch_label" >/dev/null 2>&1; then
    if ! launchctl bootout --wait "$launch_label"; then
      _zed_bridge_launch_failure "failed to unload Zed host bridge LaunchAgent"
      exit 1
    fi
  fi
  if ! launchctl bootstrap "$launch_domain" "$launch_agent"; then
    _zed_bridge_launch_failure "failed to bootstrap Zed host bridge LaunchAgent"
    exit 1
  fi
  if ! launchctl print "$launch_label" >/dev/null; then
    _zed_bridge_launch_failure "Zed host bridge LaunchAgent is unavailable after bootstrap"
    exit 1
  fi
  bridge_socket="$HOME/Library/Caches/dotgen/zed-host-bridge.sock"
  socket_ready=0
  for ((socket_attempt=0; socket_attempt<50; socket_attempt++)); do
    if [ -S "$bridge_socket" ]; then
      socket_ready=1
      break
    fi
    sleep 0.2
  done
  if [ "$socket_ready" -ne 1 ]; then
    _zed_bridge_launch_failure "Zed host bridge LaunchAgent started without creating its socket"
    exit 1
  fi
  if [ ! -O "$bridge_socket" ]; then
    _zed_bridge_launch_failure "Zed host bridge socket is not owned by the current user"
    exit 1
  fi
  chmod 0600 "$bridge_socket"
else
  log "Zed host bridge LaunchAgent installed; activation deferred until the next GUI login"
fi
"""
)

_LINUX_SETUP = (
    _RECEIVER_PREFIX
    + r"""\
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
"""
    + _SSH_SETUP.replace("SSH_TEMPLATE", "ssh-linux.conf.template").replace(
        "SSH_FORWARD_CHECK",
        r"""ssh_remote_user="$(awk '$1 == "user" { print $2; exit }' <<< "$ssh_effective")"
if [ -z "$ssh_remote_user" ]; then
  error "Zed host bridge SSH user is not effective"
  exit 1
fi
expected_forward="remoteforward /home/$ssh_remote_user/.cache/dotgen/zed-host-bridge.sock $HOME/.cache/dotgen/zed-host-bridge.sock"
grep -Fqx "$expected_forward" <<< "$ssh_effective" || {
  error "Zed host bridge RemoteForward setting is not effective"
  exit 1
}""",
    )
    + r"""

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
"""
)


@dataclass(frozen=True)
class ZedHostBridge:
    name: str = "zed_host_bridge"

    def applies_to(self, env: Environment) -> bool:
        return (env.role is EnvironmentRole.SERVER and env.os is OS.DEBIAN) or (
            env.role is EnvironmentRole.WORKSTATION and env.os in {OS.MACOS, OS.CACHYOS}
        )

    def render(self, env: Environment) -> Fragment:
        if not self.applies_to(env):
            raise ValueError(f"Zed host bridge is unsupported for {env.name}")

        configs = [ConfigFile(dest="zed-host-bridge/bridge.mjs", content=_BRIDGE)]
        if env.role is EnvironmentRole.SERVER:
            configs.extend(
                (
                    ConfigFile(dest="zed-host-bridge/zed", content=_ZED_LAUNCHER, mode=0o755),
                    ConfigFile(dest="zed-host-bridge/sshd.conf", content=_SSHD_CONFIG),
                )
            )
            return Fragment(setup=_DEBIAN_SETUP, configs=tuple(configs))

        configs.append(ConfigFile(dest="zed-host-bridge/config.json.template", content=_RECEIVER_CONFIG, mode=0o600))
        if env.os is OS.MACOS:
            configs.extend(
                (
                    ConfigFile(dest="zed-host-bridge/serve", content=_MACOS_SERVER_LAUNCHER, mode=0o755),
                    ConfigFile(dest="zed-host-bridge/ssh.conf.template", content=_MACOS_SSH_CONFIG, mode=0o600),
                    ConfigFile(dest="zed-host-bridge/dev.dotgen.zed-host-bridge.plist", content=_PLIST, mode=0o600),
                )
            )
            setup = _MACOS_SETUP
        elif env.os is OS.CACHYOS:
            configs.extend(
                (
                    ConfigFile(dest="zed-host-bridge/serve-linux", content=_LINUX_SERVER_LAUNCHER, mode=0o755),
                    ConfigFile(dest="zed-host-bridge/ssh-linux.conf.template", content=_LINUX_SSH_CONFIG, mode=0o600),
                    ConfigFile(dest="zed-host-bridge/dev.dotgen.zed-host-bridge.service", content=_SYSTEMD_UNIT),
                )
            )
            setup = _LINUX_SETUP
        else:
            raise ValueError(f"unsupported Zed host bridge receiver platform: {env.os}")
        return Fragment(setup=setup, configs=tuple(configs), secrets=frozenset({"ZED_HOST_BRIDGE_SSH_HOST"}))
