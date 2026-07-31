from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment

_DEFAULT_PROJECT = """name: <%= name %>
root: ~/repos/<%= name %>

startup_window: work
startup_pane: 0

windows:
  - work:
      layout: even-horizontal
      panes:
        - shell:
        - editor: hx .
  - claude: claude
"""

_PROJECT_HELPER = r"""#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'usage: dotgen-agent-session {init|start|reset} <project>\n' >&2
  exit 2
}

die() {
  printf 'dotgen-agent-session: %s\n' "$*" >&2
  exit 2
}

[ "$#" -eq 2 ] || usage
action="$1"
project="$2"
case "$action" in
  init|start|reset) ;;
  *) usage ;;
esac
case "$project" in
  ""|-*|agents|*[!A-Za-z0-9_-]*) die "invalid project name: $project" ;;
esac

repos="$HOME/repos"
root="$repos/$project"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
managed="$config_home/dotgen/tmuxinator/default.yml"
config_dir="$config_home/tmuxinator"
config="$config_dir/$project.yml"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/dotgen"
lock="$state_dir/tmuxinator.lock"
render_dir=""
staged=""

cleanup() {
  [ -z "$staged" ] || rm -f -- "$staged"
  [ -z "$render_dir" ] || rm -rf -- "$render_dir"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

[ -d "$repos" ] && [ ! -L "$repos" ] || die "repository directory is missing or unsafe: $repos"
[ -d "$root" ] && [ ! -L "$root" ] || die "project root is missing or unsafe: $root"
[ -f "$managed" ] && [ ! -L "$managed" ] || die "managed template is missing or unsafe: $managed"

if [ -e "$config_dir" ] || [ -L "$config_dir" ]; then
  [ -d "$config_dir" ] && [ ! -L "$config_dir" ] || die "config directory is unsafe: $config_dir"
else
  mkdir -p -- "$config_dir"
  chmod 0700 "$config_dir"
fi
validate_config() {
  if [ -e "$config" ] || [ -L "$config" ]; then
    [ -f "$config" ] && [ ! -L "$config" ] || die "project config is unsafe: $config"
  fi
}
validate_config
if [ -e "$state_dir" ] || [ -L "$state_dir" ]; then
  [ -d "$state_dir" ] && [ ! -L "$state_dir" ] || die "state directory is unsafe: $state_dir"
else
  mkdir -p -- "$state_dir"
  chmod 0700 "$state_dir"
fi

if [ -e "$lock" ] || [ -L "$lock" ]; then
  [ -f "$lock" ] && [ ! -L "$lock" ] || die "lock file is unsafe: $lock"
fi
exec 9>"$lock"
flock -x 9
validate_config

render_project() {
  render_dir="$(mktemp -d "$state_dir/tmuxinator.XXXXXX")"
  install -m 0644 "$managed" "$render_dir/default.yml"
  EDITOR=true TMUXINATOR_CONFIG="$render_dir" tmuxinator new "$project" >/dev/null
  candidate="$render_dir/$project.yml"
  [ -f "$candidate" ] && [ ! -L "$candidate" ] || die "tmuxinator did not create a safe project config"
  TMUXINATOR_CONFIG="$render_dir" tmuxinator debug "$project" >/dev/null
  staged="$(mktemp "$config_dir/.$project.yml.XXXXXX")"
  install -m 0644 "$candidate" "$staged"
  mv -f -- "$staged" "$config"
  staged=""
  rm -rf -- "$render_dir"
  render_dir=""
}

init_project() {
  if [ -e "$config" ]; then
    return 0
  fi
  if tmux has-session -t "=$project" 2>/dev/null; then
    die "tmux session already exists without a project config: $project"
  fi
  render_project
}

case "$action" in
  init)
    init_project
    printf '%s\n' "$config"
    ;;
  start)
    init_project
    flock -u 9
    exec 9>&-
    exec env TMUXINATOR_CONFIG="$config_dir" tmuxinator start "$project"
    ;;
  reset)
    if tmux has-session -t "=$project" 2>/dev/null; then
      die "refusing to reset an active project session: $project"
    fi
    render_project
    printf '%s\n' "$config"
    ;;
esac
"""

_SETUP = r"""install_package tmuxinator
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
  if [ "$DOTGEN_MODE" = diff ]; then
    if [ ! -e "$dst" ]; then
      printf '+ INSTALL %s\n' "$dst"
    elif ! cmp -s "$src" "$dst" || [ "$(stat -c '%a' "$dst")" != 755 ]; then
      printf '~ CHANGE %s\n' "$dst"
    fi
    return 0
  fi
  if [ -e "$dst" ] && cmp -s "$src" "$dst" && [ "$(stat -c '%a' "$dst")" = 755 ]; then
    return 0
  fi
  sudo install -m 0755 "$src" "$dst"
}
install_tmuxinator_helper
"""


@dataclass(frozen=True)
class Tmuxinator:
    name: str = "tmuxinator"

    def applies_to(self, env: Environment) -> bool:
        return env.name == "debian"

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP,
            configs=(
                ConfigFile(dest="tmuxinator/default.yml", content=_DEFAULT_PROJECT),
                ConfigFile(dest="tmuxinator/dotgen-agent-session", content=_PROJECT_HELPER, mode=0o755),
            ),
        )
