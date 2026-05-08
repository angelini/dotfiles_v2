from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotgen.fragment import Fragment
from dotgen.types import OS

if TYPE_CHECKING:
    from dotgen.environment import Environment

_KUBE_VERSION = "v1.35.4"
_HELM_VERSION = "v3.20.2"

_LINUX_HELPERS = (
    r"""_kube_arch() {
  case "$(detect_arch)" in
    x86_64) echo amd64 ;;
    aarch64|arm64) echo arm64 ;;
    *) error "unsupported arch: $(detect_arch)"; return 1 ;;
  esac
}
_install_kubectl_linux() {
  local arch
  arch="$(_kube_arch)"
  download_bin kubectl """
    + f'"https://dl.k8s.io/release/{_KUBE_VERSION}/bin/linux/'
    + r"""${arch}/kubectl"
}
_install_helm_linux() {
  local arch
  arch="$(_kube_arch)"
  download_tar_bin helm """
    + f'"https://get.helm.sh/helm-{_HELM_VERSION}-linux-'
    + r"""${arch}.tar.gz" "linux-${arch}/helm"
}
_install_k9s_linux() {
  local arch
  arch="$(_kube_arch)"
  download_tar_bin k9s """
    + r'"https://github.com/derailed/k9s/releases/latest/download/k9s_Linux_${arch}.tar.gz"'
    + r""" "k9s"
}
"""
)

_SETUP_MACOS = "install_packages kubectl helm k9s\n"

_SETUP_LINUX = (
    _LINUX_HELPERS
    + "_install_kubectl_linux\n"
    + "_install_helm_linux\n"
    + "_install_k9s_linux\n"
)

_SETUP_BY_OS: dict[OS, str] = {
    OS.MACOS: _SETUP_MACOS,
    OS.DEBIAN: _SETUP_LINUX,
    OS.FEDORA: _SETUP_LINUX,
}

_BASHRC = """\
[ -d "$HOME/.kube" ] && export KUBECONFIG="$HOME/.kube/config"
if bin_exists kubectl; then
  source <(kubectl completion bash)
fi
if bin_exists helm; then
  source <(helm completion bash)
fi
"""

_ALIASES = r"""alias kc='kubectl'
alias kca='kubectl get all'
alias kcn='kubectl config use-context'
alias kcr='kubectl config current-context'

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
"""


@dataclass(frozen=True)
class Kubectl:
    name: str = "kubectl"

    def applies_to(self, env: "Environment") -> bool:
        return True

    def render(self, env: "Environment") -> Fragment:
        return Fragment(
            setup=_SETUP_BY_OS[env.os],
            bashrc=_BASHRC,
            alias=_ALIASES,
        )
