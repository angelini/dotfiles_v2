from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment

_SETUP = r"""history_file="$HOME/.bash_history"
if [ -L "$history_file" ] || { [ -e "$history_file" ] && [ ! -f "$history_file" ]; }; then
  error "unsafe Bash history path (expected a regular non-symlink file): $history_file"
  exit 1
fi
if [ ! -e "$history_file" ]; then
  if ! (umask 077; set -o noclobber; : > "$history_file") 2>/dev/null; then
    error "unable to create Bash history file safely: $history_file"
    exit 1
  fi
fi
if [ -L "$history_file" ] || [ ! -f "$history_file" ]; then
  error "unsafe Bash history path (expected a regular non-symlink file): $history_file"
  exit 1
fi
if ! chmod 0600 "$history_file"; then
  error "unable to secure Bash history file: $history_file"
  exit 1
fi
"""

_BASHRC = r"""HISTFILE=~/.bash_history
HISTSIZE=100000
HISTFILESIZE=100000
HISTCONTROL=ignoreboth
shopt -s histappend

__dotgen_history_sync() {
  local status=$?
  history -a
  history -n
  return "$status"
}
case ";${PROMPT_COMMAND:-};" in
  *";__dotgen_history_sync;"*|*"; __dotgen_history_sync;"*) ;;
  *) PROMPT_COMMAND="__dotgen_history_sync${PROMPT_COMMAND:+;${PROMPT_COMMAND}}" ;;
esac

if [ "${__DOTGEN_FZF_BASH_INITIALIZED:-0}" != 1 ]; then
  if bin_exists fzf; then
    case " ${FZF_CTRL_R_OPTS-} " in
      *" --no-sort "*) ;;
      *) FZF_CTRL_R_OPTS="${FZF_CTRL_R_OPTS:+${FZF_CTRL_R_OPTS} }--no-sort" ;;
    esac
    export FZF_CTRL_R_OPTS
    if __dotgen_fzf_bash_init="$(fzf --bash)" && eval "$__dotgen_fzf_bash_init"; then
      __DOTGEN_FZF_BASH_INITIALIZED=1
    elif [ "${__DOTGEN_FZF_BASH_WARNED:-0}" != 1 ]; then
      printf 'warning: fzf Bash integration failed; using native Bash history search\n' >&2
      __DOTGEN_FZF_BASH_WARNED=1
    fi
    unset __dotgen_fzf_bash_init
  elif [ "${__DOTGEN_FZF_BASH_WARNED:-0}" != 1 ]; then
    printf 'warning: fzf is unavailable; using native Bash history search\n' >&2
    __DOTGEN_FZF_BASH_WARNED=1
  fi
fi
"""


@dataclass(frozen=True)
class FzfBashHistory:
    name: str = "fzf_bash_history"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP, bashrc=_BASHRC)
