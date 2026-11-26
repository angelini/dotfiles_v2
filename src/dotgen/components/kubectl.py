from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS, EnvironmentRole

_KUBE_VERSION = "v1.35.11"
_KUBELOGIN_VERSION = "v1.36.4"
_KUBELOGIN_SHA256 = {
    "amd64": "9e8baeb4905d35a301304af2548324997add512fe94ab20e65993d167212bf85",
    "arm64": "669c2d3bcc6766351ad5a7b03971792b4e7a55117b335a12d9858d43a525d9dc",
}
_TALOSCTL_OIDC_VERSION = "v0.1.2"
_TALOSCTL_OIDC_SHA256 = {
    "amd64": "776a34039accd196222bcfa5b1dcd428677f5faf4d48df74da3143a384e3130b",
    "arm64": "491c9af5e6e7b3adff1191da25d7fabcb78fd73012ba8b091112a7272ebf6540",
}
_ARGOCD_VERSION = "v3.6.3"
_ARGOCD_BUILD = f"{_ARGOCD_VERSION}+b4accc4"
_ARGOCD_SHA256 = {
    "amd64": "3750cd7ed2a2ef05c640344b86f29aa99c9783e847c8f326c81e3900ad39412b",
    "arm64": "04a7b681d6c5eec193159705c5556114f8cba98abada4c17c3991124065e1964",
}
_HELM_VERSION = "v4.3.2"
_K9S_VERSION = "v0.51.0"
_KUBECTX_VERSION = "v0.11.0"
_KUBIE_VERSION = "v0.28.0"
_KIND_VERSION = "v0.33.0"
_KIND_SHA256 = {
    "amd64": "aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d",
    "arm64": "20022bee6cfcd5086cb7234d218e3454e6090022f2a8f55d1fa7fcf42c3867a2",
}
_K0SCTL_VERSION = "v0.33.1"
_K0SCTL_SHA256 = {
    "amd64": "bd5cd9125c93d8d30c33f7b2f3693fed0d74140a248d433dad74f2b7015295b5",
    "arm64": "3632072361f3e83dde9b34f83eea49673d3bfe84763cf361edc3aec7209231a6",
}

_TALOSCTL_VERSION = "v1.14.2"
_TALOSCTL_SHA256 = {
    "amd64": "c6c9552b0e5f767352c595fa1c0af4f186f697488646872955057d23990a66c4",
    "arm64": "5b7119f9cc68c1e6dcd394564208a9ae417c5cc9e8e2585fa173082e53f5e6d7",
}

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
    + r"""
}
_install_k0sctl_linux() {
  local arch checksum
  arch="$(_kube_arch)"
  case "$arch" in
"""
    + f'    amd64) checksum="{_K0SCTL_SHA256["amd64"]}" ;;\n'
    + f'    arm64) checksum="{_K0SCTL_SHA256["arm64"]}" ;;\n'
    + r"""  esac
  download_bin_sha256 k0sctl """
    + f'"https://github.com/k0sproject/k0sctl/releases/download/{_K0SCTL_VERSION}/k0sctl-linux-'
    + r'${arch}" "$checksum" '
    + f'"{_K0SCTL_VERSION}" version'
    + "\n}\n"
)

_KIND_SETUP_LINUX = (
    r"""_install_kind_linux() {
  local arch checksum
  arch="$(_kube_arch)"
  case "$arch" in
"""
    + f'    amd64) checksum="{_KIND_SHA256["amd64"]}" ;;\n'
    + f'    arm64) checksum="{_KIND_SHA256["arm64"]}" ;;\n'
    + r"""  esac
  download_bin_sha256 kind """
    + f'"https://github.com/kubernetes-sigs/kind/releases/download/{_KIND_VERSION}/kind-linux-'
    + r'${arch}" "$checksum" '
    + f'"{_KIND_VERSION}" version'
    + "\n}\n_install_kind_linux\n"
)

_TALOSCTL_SETUP_LINUX = (
    r"""_install_talosctl_linux() {
  local arch checksum
  arch="$(_kube_arch)"
  case "$arch" in
"""
    + f'    amd64) checksum="{_TALOSCTL_SHA256["amd64"]}" ;;\n'
    + f'    arm64) checksum="{_TALOSCTL_SHA256["arm64"]}" ;;\n'
    + r"""  esac
  download_bin_sha256 talosctl """
    + f'"https://github.com/siderolabs/talos/releases/download/{_TALOSCTL_VERSION}/talosctl-linux-'
    + r'${arch}" "$checksum" '
    + f'"{_TALOSCTL_VERSION}" version --client --short'
    + "\n}\n_install_talosctl_linux\n"
)

_KUBELOGIN_SETUP_LINUX = (
    r"""_install_kubelogin_linux() {
  local arch checksum
  arch="$(_kube_arch)"
  case "$arch" in
"""
    + f'    amd64) checksum="{_KUBELOGIN_SHA256["amd64"]}" ;;\n'
    + f'    arm64) checksum="{_KUBELOGIN_SHA256["arm64"]}" ;;\n'
    + r"""  esac
  download_zip_bin_sha256 kubectl-oidc_login """
    + f'"https://github.com/int128/kubelogin/releases/download/{_KUBELOGIN_VERSION}/kubelogin_linux_'
    + r'${arch}.zip" "$checksum" kubelogin '
    + f'"{_KUBELOGIN_VERSION}" --version'
    + "\n}\n_install_kubelogin_linux\n"
)

_TALOSCTL_OIDC_SETUP_LINUX = (
    r"""_install_talosctl_oidc_linux() {
  local arch checksum
  arch="$(_kube_arch)"
  case "$arch" in
"""
    + f'    amd64) checksum="{_TALOSCTL_OIDC_SHA256["amd64"]}" ;;\n'
    + f'    arm64) checksum="{_TALOSCTL_OIDC_SHA256["arm64"]}" ;;\n'
    + r"""  esac
  download_bin_sha256 talosctl-oidc """
    + f'"https://github.com/qjoly/talosctl-oidc/releases/download/{_TALOSCTL_OIDC_VERSION}/talosctl-oidc-linux-'
    + r'${arch}" "$checksum" '
    + f'"{_TALOSCTL_OIDC_VERSION}" version'
    + "\n}\n_install_talosctl_oidc_linux\n"
)

_ARGOCD_SETUP_LINUX = (
    r"""_install_argocd_linux() {
  local arch checksum
  arch="$(_kube_arch)"
  case "$arch" in
"""
    + f'    amd64) checksum="{_ARGOCD_SHA256["amd64"]}" ;;\n'
    + f'    arm64) checksum="{_ARGOCD_SHA256["arm64"]}" ;;\n'
    + r"""  esac
  download_bin_sha256 argocd """
    + f'"https://github.com/argoproj/argo-cd/releases/download/{_ARGOCD_VERSION}/argocd-linux-'
    + r'${arch}" "$checksum" '
    + f'"{_ARGOCD_BUILD}" version --client --short'
    + "\n}\n_install_argocd_linux\n"
)

_SETUP_MACOS = "install_packages kubectl helm k9s kubectx kubie kind k0sproject/tap/k0sctl talosctl argocd kubelogin qjoly/tap/talosctl-oidc\n"

_SETUP_LINUX = (
    "install_package unzip\n"
    + _LINUX_HELPERS
    + "_install_kubectl_linux\n"
    + _KUBELOGIN_SETUP_LINUX
    + "_install_helm_linux\n"
    + "_install_k9s_linux\n"
    + "_install_kubectx_linux\n"
    + "_install_kubens_linux\n"
    + "_install_kubie_linux\n"
    + "_install_k0sctl_linux\n"
    + _TALOSCTL_SETUP_LINUX
    + _TALOSCTL_OIDC_SETUP_LINUX
    + _ARGOCD_SETUP_LINUX
)

_SETUP_BY_OS: dict[OS, str] = {
    OS.CACHYOS: _SETUP_LINUX,
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

_KIND_BASHRC = """\
if bin_exists kind; then
  source <(kind completion bash)
fi
"""

_ALIASES = r"""alias kc='kubectl'
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
"""


@dataclass(frozen=True)
class Kubectl:
    name: str = "kubectl"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        setup = _SETUP_BY_OS[env.os]
        bashrc = _BASHRC
        if env.role is not EnvironmentRole.CONTAINER:
            if env.os is not OS.MACOS:
                setup += _KIND_SETUP_LINUX
            bashrc += _KIND_BASHRC
        return Fragment(setup=setup, bashrc=bashrc, alias=_ALIASES)
