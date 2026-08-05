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
alias kx='kubectx'
alias kns='kubens'

pod_names() {
  kubectl get pods -o name "$@" | sed 's|^pod/||'
}

k8s_secrets() {
  local ns="${1}"
  local secret="${2}"
  kubectl -n "${ns}" get secret "${secret}" -o json \
    | jq '.data | to_entries | map({key: .key, value: .value|@base64d}) | from_entries'
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

# --- gcloud ---
alias gcp='gcloud config configurations activate default'

get_project_roles() {
  local account="${1}"
  local project
  project="$(gcloud config get project)"
  gcloud projects get-iam-policy "${project}" \
    --flatten="bindings[].members" \
    --format="table(bindings.role)" \
    --filter="bindings.members:${account}"
}

get_sa_bindings() {
  local account="${1}"
  gcloud iam service-accounts get-iam-policy "${account}" \
    --flatten="bindings[].members" \
    --format="table(bindings.role, bindings.members)"
}

# --- dotfiles_deploy ---
[ -r "$HOME/.config/dotgen/private-aliases.sh" ] && source "$HOME/.config/dotgen/private-aliases.sh"

