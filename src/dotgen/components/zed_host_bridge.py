from dataclasses import dataclass
from pathlib import Path

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS

_RESOURCE_ROOT = Path(__file__).resolve().parents[1] / "resources" / "zed_host_bridge"


def _resource_text(name: str) -> str:
    return (_RESOURCE_ROOT / name).read_text()


_BRIDGE = _resource_text("bridge.mjs")
_ZED_LAUNCHER = _resource_text("zed")
_SERVER_LAUNCHER = _resource_text("serve")
_PLIST = _resource_text("dev.dotgen.zed-host-bridge.plist")
_SSH_CONFIG = _resource_text("ssh.conf.template")
_RECEIVER_CONFIG = _resource_text("config.json.template")

_COMMON_SETUP = r"""\
_zed_bridge_assert_dir() {
  local directory=$1
  if [ -L "$directory" ] || { [ -e "$directory" ] && [ ! -d "$directory" ]; }; then
    error "unsafe Zed host bridge directory: $directory"
    return 1
  fi
  mkdir -p -- "$directory"
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
  if [ -L "$destination" ] || { [ -e "$destination" ] && [ ! -f "$destination" ]; }; then
    error "unsafe Zed host bridge destination: $destination"
    return 1
  fi
  staging="$(mktemp "$parent/.dotgen-zed-host-bridge.XXXXXX")"
  if ! install -m "$mode" "$source" "$staging"; then
    rm -f -- "$staging"
    return 1
  fi
  if [ -L "$destination" ] || { [ -e "$destination" ] && [ ! -f "$destination" ]; }; then
    rm -f -- "$staging"
    error "unsafe Zed host bridge destination: $destination"
    return 1
  fi
  mv -f -- "$staging" "$destination"
}

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
"""
)

_MACOS_SETUP = (
    r"""\
load_secrets
zed_bridge_ssh_host=${ZED_HOST_BRIDGE_SSH_HOST:-}
if [ "${#zed_bridge_ssh_host}" -gt 255 ] || ! [[ "$zed_bridge_ssh_host" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  error "ZED_HOST_BRIDGE_SSH_HOST must be an exact SSH alias containing only ASCII letters, digits, dots, and hyphens"
  exit 1
fi
"""
    + _COMMON_SETUP
    + r"""\
_zed_bridge_install_file "$DIR/config/zed-host-bridge/serve" "$HOME/.local/libexec/dotgen/zed-host-bridge-serve" 0755
_zed_bridge_assert_dir "${XDG_CONFIG_HOME:-$HOME/.config}"
_zed_bridge_safe_dir "${XDG_CONFIG_HOME:-$HOME/.config}/dotgen" 0700
receiver_config="${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/zed-host-bridge.json"
if [ -L "$receiver_config" ] || { [ -e "$receiver_config" ] && [ ! -f "$receiver_config" ]; }; then
  error "unsafe Zed host bridge destination: $receiver_config"
  exit 1
fi
install_config_template "$DIR/config/zed-host-bridge/config.json.template" "$receiver_config" 'ZED_HOST_BRIDGE_SSH_HOST' 0600

_zed_bridge_assert_dir "$HOME/Library"
_zed_bridge_assert_dir "$HOME/Library/Caches"
_zed_bridge_safe_dir "$HOME/Library/Caches/dotgen" 0700
_zed_bridge_assert_dir "$HOME/Library/LaunchAgents"
launch_agent="$HOME/Library/LaunchAgents/dev.dotgen.zed-host-bridge.plist"
_zed_bridge_install_file "$DIR/config/zed-host-bridge/dev.dotgen.zed-host-bridge.plist" "$launch_agent" 0600

_zed_bridge_safe_dir "$HOME/.ssh" 0700
_zed_bridge_safe_dir "$HOME/.ssh/config.d" 0700
ssh_include="$HOME/.ssh/config.d/dotgen-zed-host-bridge.conf"
if [ -L "$ssh_include" ] || { [ -e "$ssh_include" ] && [ ! -f "$ssh_include" ]; }; then
  error "unsafe Zed host bridge SSH include destination: $ssh_include"
  exit 1
fi
install_config_template "$DIR/config/zed-host-bridge/ssh.conf.template" "$ssh_include" 'ZED_HOST_BRIDGE_SSH_HOST' 0600
chmod 0600 "$ssh_include"

ssh_main="$HOME/.ssh/config"
managed_include='Include ~/.ssh/config.d/dotgen-zed-host-bridge.conf'
if [ -L "$ssh_main" ] || { [ -e "$ssh_main" ] && [ ! -f "$ssh_main" ]; }; then
  error "unsafe SSH config destination: $ssh_main"
  exit 1
fi
if [ -e "$ssh_main" ] && [ "$(stat -f '%u' "$ssh_main")" != "$(id -u)" ]; then
  error "SSH config is not owned by the current user: $ssh_main"
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
if [ -L "$ssh_main" ] || { [ -e "$ssh_main" ] && [ ! -f "$ssh_main" ]; }; then
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
grep -Fqx 'streamlocalbindunlink yes' <<< "$ssh_effective" || { error "Zed host bridge StreamLocalBindUnlink setting is not effective"; exit 1; }
grep -Fqx 'streamlocalbindmask 0177' <<< "$ssh_effective" || { error "Zed host bridge StreamLocalBindMask setting is not effective"; exit 1; }
grep -E '^remoteforward /home/[^/]+/\.cache/dotgen/zed-host-bridge\.sock .*/Library/Caches/dotgen/zed-host-bridge\.sock$' <<< "$ssh_effective" >/dev/null || {
  error "Zed host bridge RemoteForward setting is not effective"
  exit 1
}

launch_domain="gui/$(id -u)"
launch_label="$launch_domain/dev.dotgen.zed-host-bridge"
if launchctl print "$launch_domain" >/dev/null 2>&1; then
  launchctl bootout "$launch_label" >/dev/null 2>&1 || true
  launchctl bootstrap "$launch_domain" "$launch_agent"
  launchctl kickstart -k "$launch_label"
  launchctl print "$launch_label" >/dev/null
  bridge_socket="$HOME/Library/Caches/dotgen/zed-host-bridge.sock"
  socket_ready=0
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if [ -S "$bridge_socket" ]; then
      socket_ready=1
      break
    fi
    sleep 0.2
  done
  if [ "$socket_ready" -ne 1 ]; then
    error "Zed host bridge LaunchAgent started without creating its socket; inspect: launchctl print $launch_label"
    exit 1
  fi
  chmod 0600 "$bridge_socket"
else
  log "Zed host bridge LaunchAgent installed; activation deferred until the next GUI login"
fi
"""
)


@dataclass(frozen=True)
class ZedHostBridge:
    name: str = "zed_host_bridge"

    def applies_to(self, env: Environment) -> bool:
        return env.name in {"debian", "macos"}

    def render(self, env: Environment) -> Fragment:
        configs = [ConfigFile(dest="zed-host-bridge/bridge.mjs", content=_BRIDGE)]
        if env.os is OS.MACOS:
            configs.extend(
                (
                    ConfigFile(dest="zed-host-bridge/serve", content=_SERVER_LAUNCHER, mode=0o755),
                    ConfigFile(dest="zed-host-bridge/config.json.template", content=_RECEIVER_CONFIG, mode=0o600),
                    ConfigFile(dest="zed-host-bridge/ssh.conf.template", content=_SSH_CONFIG, mode=0o600),
                    ConfigFile(dest="zed-host-bridge/dev.dotgen.zed-host-bridge.plist", content=_PLIST, mode=0o600),
                )
            )
            return Fragment(setup=_MACOS_SETUP, configs=tuple(configs), secrets=frozenset({"ZED_HOST_BRIDGE_SSH_HOST"}))
        configs.append(ConfigFile(dest="zed-host-bridge/zed", content=_ZED_LAUNCHER, mode=0o755))
        return Fragment(setup=_DEBIAN_SETUP, configs=tuple(configs))
