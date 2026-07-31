from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_SETUP = "install_package mosh\n"

_ALIAS_BY_OS: dict[OS, str] = {
    OS.DEBIAN: "",
    OS.MACOS: """\
mosh-agent() {
  if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    printf 'usage: mosh-agent <host> [session]\\n' >&2
    return 2
  fi
  local host="$1" session="${2-agents}"
  case "$host" in
    ""|-*)
      printf 'mosh-agent: invalid host: %s\\n' "$host" >&2
      return 2
      ;;
  esac
  case "$session" in
    ""|*[!A-Za-z0-9_-]*)
      printf 'mosh-agent: invalid session name: %s\\n' "$session" >&2
      return 2
      ;;
  esac
  command mosh -- "$host" tmux new-session -A -s "$session"
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
