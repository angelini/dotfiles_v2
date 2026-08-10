from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment

_CONFIG = r"""set -g default-terminal "tmux-256color"
set -as terminal-features ",xterm-ghostty:RGB:clipboard"
set -as terminal-features ",xterm-256color:RGB:clipboard"
set -as terminal-features ",xterm:RGB:clipboard"
set -as terminal-overrides ",xterm-256color:Ms=\\E]52;c%p1%s;%p2%s\\007"
set -as terminal-overrides ",xterm:Ms=\\E]52;c%p1%s;%p2%s\\007"
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
set -g status-style "bg=#efefef,fg=#4d4d4c"
set -g status-left-length 40
set -g status-right-length 80
set -g status-left "#[fg=#ffffff,bg=#4271ae,bold] #S #[fg=#4271ae,bg=#efefef,nobold]"
set -g status-right "#[fg=#3e999f,bg=#efefef]#[fg=#ffffff,bg=#3e999f] #H #[fg=#4271ae,bg=#3e999f]#[fg=#ffffff,bg=#4271ae,bold] %a %H:%M "
setw -g window-status-separator ""
setw -g window-status-format "#[fg=#8e908c,bg=#efefef] #I:#W#F "
setw -g window-status-current-format "#[fg=#8959a8,bg=#efefef]#[fg=#ffffff,bg=#8959a8,bold] #I:#W#F #[fg=#8959a8,bg=#efefef,nobold]"
set -g pane-border-style "fg=#d6d6d6"
set -g pane-active-border-style "fg=#4271ae"
set -g message-style "bg=#eab700,fg=#4d4d4c,bold"
set -g mode-style "bg=#4271ae,fg=#ffffff,bold"
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
