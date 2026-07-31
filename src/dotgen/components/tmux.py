from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment

_CONFIG = r"""set -g default-terminal "tmux-256color"
set -as terminal-features ",xterm-ghostty:RGB:clipboard"
set -as terminal-features ",xterm-256color:RGB:clipboard"
set -as terminal-features ",xterm:RGB:clipboard"
set -as terminal-overrides ",xterm-256color:Ms=\\E]52;c;%p2%s\\007"
set -as terminal-overrides ",xterm:Ms=\\E]52;c;%p2%s\\007"
set -s set-clipboard on
set -s escape-time 10
set -g focus-events on
set -g mouse on
set -g history-limit 100000
"""

_SETUP = """\
install_package tmux
install_config "$DIR/config/tmux/tmux.conf" "$HOME/.tmux.conf"
"""

_ALIAS = """\
ta() {
  if [ "$#" -gt 1 ]; then
    printf 'usage: ta [session]\\n' >&2
    return 2
  fi
  local session="${1-agents}"
  case "$session" in
    ""|*[!A-Za-z0-9_-]*)
      printf 'ta: invalid session name: %s\\n' "$session" >&2
      return 2
      ;;
  esac
  if [ -n "${TMUX:-}" ]; then
    if ! command tmux has-session -t "=$session" 2>/dev/null; then
      command tmux new-session -d -s "$session" || return
    fi
    command tmux switch-client -t "=$session"
  else
    command tmux new-session -A -s "$session"
  fi
}
"""


@dataclass(frozen=True)
class Tmux:
    name: str = "tmux"

    def applies_to(self, env: Environment) -> bool:
        return env.name in {"debian", "macos"}

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP,
            alias=_ALIAS,
            configs=(ConfigFile(dest="tmux/tmux.conf", content=_CONFIG),),
        )
