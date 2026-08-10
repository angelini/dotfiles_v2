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

# --- kubectl ---
alias kc='kubectl'
alias kcn='kubectl ns'
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

# --- dotfiles_deploy ---
[ -r "${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/private-aliases.sh" ] && source "${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/private-aliases.sh"

