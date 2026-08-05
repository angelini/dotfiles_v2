from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_KUBE_VERSION = "v1.35.4"
_HELM_VERSION = "v3.20.2"
_K9S_VERSION = "v0.51.0"
_KUBECTX_VERSION = "v0.11.0"
_KUBIE_VERSION = "v0.27.0"

_LINUX_HELPERS = (
    r"""_kube_arch() {
  case "$(detect_arch)" in
    x86_64) echo amd64 ;;
    aarch64|arm64) echo arm64 ;;
    *) error "unsupported arch: $(detect_arch)"; return 1 ;;
  esac
}
_kubectx_arch() {
  case "$(detect_arch)" in
    x86_64) echo x86_64 ;;
    aarch64|arm64) echo arm64 ;;
    *) error "unsupported arch: $(detect_arch)"; return 1 ;;
  esac
}
_kubie_arch() {
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
    + r'${arch}/kubectl" '
    + f'"{_KUBE_VERSION}" version --client'
    + r"""
}
_install_helm_linux() {
  local arch
  arch="$(_kube_arch)"
  download_tar_bin helm """
    + f'"https://get.helm.sh/helm-{_HELM_VERSION}-linux-'
    + r'${arch}.tar.gz" "linux-${arch}/helm" '
    + f"\"{_HELM_VERSION}\" version --template '{{{{.Version}}}}'"
    + r"""
}
_install_k9s_linux() {
  local arch
  arch="$(_kube_arch)"
  download_tar_bin k9s """
    + f'"https://github.com/derailed/k9s/releases/download/{_K9S_VERSION}/k9s_Linux_'
    + r'${arch}.tar.gz" "k9s" '
    + f'"{_K9S_VERSION}" version --short'
    + r"""
}
_install_kubectx_linux() {
  local arch
  arch="$(_kubectx_arch)"
  download_tar_bin kubectx """
    + f'"https://github.com/ahmetb/kubectx/releases/download/{_KUBECTX_VERSION}/kubectx_{_KUBECTX_VERSION}_linux_'
    + r'${arch}.tar.gz" "kubectx" '
    + f'"{_KUBECTX_VERSION}" --version'
    + r"""
}
_install_kubens_linux() {
  local arch
  arch="$(_kubectx_arch)"
  download_tar_bin kubens """
    + f'"https://github.com/ahmetb/kubectx/releases/download/{_KUBECTX_VERSION}/kubens_{_KUBECTX_VERSION}_linux_'
    + r'${arch}.tar.gz" "kubens" '
    + f'"{_KUBECTX_VERSION}" --version'
    + r"""
}
_install_kubie_linux() {
  local arch
  arch="$(_kubie_arch)"
  download_bin kubie """
    + f'"https://github.com/sbstp/kubie/releases/download/{_KUBIE_VERSION}/kubie-linux-'
    + r'${arch}" '
    + f'"{_KUBIE_VERSION.removeprefix("v")}" --version'
    + "\n}\n"
)

_SETUP_MACOS = "install_packages kubectl helm k9s kubectx kubie\n"

_SETUP_LINUX = _LINUX_HELPERS + "_install_kubectl_linux\n" + "_install_helm_linux\n" + "_install_k9s_linux\n" + "_install_kubectx_linux\n" + "_install_kubens_linux\n" + "_install_kubie_linux\n"

_SETUP_BY_OS: dict[OS, str] = {
    OS.MACOS: _SETUP_MACOS,
    OS.DEBIAN: _SETUP_LINUX,
}

_BASHRC = """\
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
"""

_ALIASES = r"""alias kc='kubectl'
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
"""


@dataclass(frozen=True)
class Kubectl:
    name: str = "kubectl"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP_BY_OS[env.os],
            bashrc=_BASHRC,
            alias=_ALIASES,
        )
