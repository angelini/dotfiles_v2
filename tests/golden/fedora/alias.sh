# alias.sh — sourced by ~/.bashrc
# --- bash_base ---
alias klear='clear && printf "\033[3J"'
alias rgc='rg -C 30'
alias ip='curl -s ifconfig.me'

# git
alias gs='git status'
alias ga='git add'
alias gc='git commit'
alias gpo='git push origin'
alias gpfo='git push --force-with-lease origin'
alias gl='git log --color --graph --pretty=format:"%Cred%h%Creset -%C(yellow)%d%Creset %s %Cgreen(%cr) %C(bold blue)<%an>%Creset" --abbrev-commit'
alias l='ls -hlA --color=auto'

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

