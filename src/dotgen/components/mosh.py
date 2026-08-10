from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_SETUP = "install_package mosh\n"

_ALIAS_BY_OS: dict[OS, str] = {
    OS.DEBIAN: "",
    OS.MACOS: """\
mosh-agent() {
  local kill_session=0
  if [ "${1-}" = -k ]; then
    kill_session=1
    shift
  fi
  if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    printf 'usage: mosh-agent [-k] <host> [project]\\n' >&2
    return 2
  fi
  local host="$1" project="${2-}"
  case "$host" in
    ""|-*)
      printf 'mosh-agent: invalid host: %s\\n' "$host" >&2
      return 2
      ;;
  esac
  if [ "$#" -eq 1 ]; then
    if [ "$kill_session" -eq 1 ]; then
      command mosh -- "$host" tmux kill-session -t "=dev"
    else
      command mosh -- "$host" tmux new-session -A -s dev
    fi
    return
  fi
  case "$project" in
    ""|-*|dev|*[!A-Za-z0-9_-]*)
      printf 'mosh-agent: invalid project name: %s\\n' "$project" >&2
      return 2
      ;;
  esac
  local action="start"
  [ "$kill_session" -eq 0 ] || action="kill"
  command mosh -- "$host" /usr/local/bin/dotgen-agent-session "$action" "$project"
}
""",
}


@dataclass(frozen=True)
class Mosh:
    name: str = "mosh"

    def applies_to(self, env: Environment) -> bool:
        return env.name in {"debian", "macos"}

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP, alias=_ALIAS_BY_OS[env.os])
