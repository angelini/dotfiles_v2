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
if [ -d "/opt/homebrew/bin" ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi
[ -r "$HOME/.orbstack/shell/init.bash" ] && source "$HOME/.orbstack/shell/init.bash"

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

# --- python_tools ---
[ -f "$HOME/.local/bin/env" ] && source "$HOME/.local/bin/env"

# --- rust ---
[ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env"

# --- node_fnm ---
export PATH="$HOME/.local/share/fnm:$PATH"
if bin_exists fnm; then
  eval "$(fnm env --use-on-cd --shell bash)"
fi

# --- postgres ---
export PATH="/opt/homebrew/opt/postgresql@18/bin:$PATH"

# --- go_lang ---
export GOPATH="${GOPATH:-$HOME/go}"
export GOROOT="$HOME/.local/share/go"
export PATH="$GOROOT/bin:$GOPATH/bin:$PATH"

# --- gcloud ---
for _f in \
  "/opt/homebrew/share/google-cloud-sdk/path.bash.inc" \
  "/opt/homebrew/share/google-cloud-sdk/completion.bash.inc" \
  "/usr/lib/google-cloud-sdk/path.bash.inc" \
  "/usr/lib/google-cloud-sdk/completion.bash.inc"; do
  [ -f "$_f" ] && source "$_f"
done
unset _f

# --- aws ---
if bin_exists aws_completer; then
  complete -C "$(command -v aws_completer)" aws
fi

