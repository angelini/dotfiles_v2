# .bashrc
case $- in
  *i*) ;;
  *) return ;;
esac

export PATH="$HOME/bin:$HOME/.local/bin:$PATH"
bin_exists() { command -v "$1" >/dev/null 2>&1; }
[ -f "$HOME/.aliases" ] && source "$HOME/.aliases"
# --- bash_base ---
ulimit -n 65536

export COLORTERM="${COLORTERM:-truecolor}"

set_win_title() {
  local status=$?
  printf '\033]0;%s@%s:%s\007' "${USER:-?}" "${HOSTNAME%%.*}" "${PWD/#$HOME/~}"
  return "$status"
}
case ";${PROMPT_COMMAND:-};" in
  *";set_win_title;"*|*"; set_win_title;"*) ;;
  *) PROMPT_COMMAND="set_win_title${PROMPT_COMMAND:+;${PROMPT_COMMAND}}" ;;
esac

epoch() {
  python3 - "$1" <<'PYEOF'
import sys, datetime as d
print(d.datetime.fromtimestamp(int(sys.argv[1])).isoformat())
PYEOF
}

# --- fzf_bash_history ---
HISTFILE=~/.bash_history
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

# --- helix ---
export EDITOR=hx
export VISUAL=hx

# --- starship ---
if bin_exists starship; then
  eval "$(starship init bash)"
fi

# --- zoxide ---
if bin_exists zoxide; then
  eval "$(zoxide init bash)"
fi

# --- kubectl ---
[ -d "$HOME/.kube" ] && export KUBECONFIG="$HOME/.kube/config"
if bin_exists kubectl; then
  source <(kubectl completion bash)
fi
if bin_exists helm; then
  source <(helm completion bash)
fi
if bin_exists kubie; then
  source <(kubie generate-completion)
fi

# --- node_fnm ---
export PATH="$HOME/.local/share/fnm:$PATH"
if bin_exists fnm; then
  eval "$(fnm env --use-on-cd --shell bash)"
fi

