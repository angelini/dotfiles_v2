# alias.sh — sourced by ~/.bashrc
# --- bash_base ---
alias klear='clear && printf "\033[3J"'
alias rgc='rg -C 30'
alias ip='curl -s ifconfig.me'

# git
alias gs='git status'
alias gc='git checkout'
alias ga='git commit --amend --no-edit'
alias gpo='git push origin $(git rev-parse --abbrev-ref HEAD)'
alias gpfo='git push origin +$(git rev-parse --abbrev-ref HEAD)'
alias gl="git log --graph --pretty=format:'%Cred%h%Creset %Creset%Cblue%an%Creset %s %Cgreen(%cr)%Cred%d%Creset' --abbrev-commit --date=relative --max-count=25"
alias l='eza --long --all --group-directories-first --git'

# --- tmux ---
ta() {
  if [ "$#" -gt 1 ]; then
    printf 'usage: ta [session]\n' >&2
    return 2
  fi
  local session="${1-dev}"
  case "$session" in
    ""|*[!A-Za-z0-9_-]*)
      printf 'ta: invalid session name: %s\n' "$session" >&2
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

# --- kubectl ---
alias kc='kubectl'
alias kca='kubectl get all'
alias kcn='kubectl config use-context'
alias kcr='kubectl config current-context'
alias kx='kubectx'
alias kns='kubens'

pod_names() {
  kubectl get pods -o name "$@" | sed 's|^pod/||'
}

k8s_secrets() {
  kubectl get secrets "$@" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
}

k8s_env() {
  kubectl exec "$1" -- env
}

k8s_events() {
  kubectl get events --sort-by='.lastTimestamp' "$@"
}

k8s_all_resources_in_ns() {
  local ns="${1:?usage: k8s_all_resources_in_ns <namespace>}"
  kubectl api-resources --verbs=list --namespaced -o name \
    | xargs -n 1 kubectl get --show-kind --ignore-not-found -n "$ns"
}

# --- pi_agent ---
pi() {
  pi-sandbox "$@"
}

pi-unsafe() {
  command pi "$@"
}

