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

set_win_title() {
  printf '\033]0;%s@%s:%s\007' "${USER:-?}" "${HOSTNAME%%.*}" "${PWD/#$HOME/~}"
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

# --- stinkpot ---
if bin_exists stinkpot; then
  export HISTFILE=/dev/null
  eval "$(stinkpot init)"
else
  printf 'warning: stinkpot is unavailable; using Bash history defaults\n' >&2
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

