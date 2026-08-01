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
set -g detach-on-destroy off
set -g base-index 1
set -g renumber-windows on
set -g status-position bottom
set -g status-justify left
set -g status-interval 5
set -g status-style "bg=#1d1f21,fg=#c5c8c6"
set -g status-left-length 40
set -g status-right-length 80
set -g status-left "#[fg=#1d1f21,bg=#81a2be,bold] #S #[fg=#81a2be,bg=#1d1f21,nobold]"
set -g status-right "#[fg=#8abeb7,bg=#1d1f21]#[fg=#1d1f21,bg=#8abeb7] #H #[fg=#81a2be,bg=#8abeb7]#[fg=#1d1f21,bg=#81a2be,bold] %a %H:%M "
setw -g window-status-separator ""
setw -g window-status-format "#[fg=#969896,bg=#1d1f21] #I:#W#F "
setw -g window-status-current-format "#[fg=#1d1f21,bg=#b294bb]#[fg=#1d1f21,bg=#b294bb,bold] #I:#W#F #[fg=#b294bb,bg=#1d1f21,nobold]"
set -g message-style "bg=#f0c674,fg=#1d1f21,bold"
set -g mode-style "bg=#81a2be,fg=#1d1f21,bold"
bind r source-file ~/.tmux.conf \; display-message "tmux config reloaded"
bind | split-window -h -c "#{pane_current_path}"
bind - split-window -v -c "#{pane_current_path}"
bind c new-window -c "#{pane_current_path}"
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
  local session="${1-dev}"
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
