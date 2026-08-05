from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_SETUP_MACOS = "install_cask google-cloud-sdk\n"

_SETUP_DEBIAN = """add_repo apt google-cloud-sdk \\
  "deb [signed-by=/etc/apt/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \\
  "https://packages.cloud.google.com/apt/doc/apt-key.gpg"
update_pkg_index
install_package google-cloud-cli
"""

_SETUP_BY_OS: dict[OS, str] = {
    OS.MACOS: _SETUP_MACOS,
    OS.DEBIAN: _SETUP_DEBIAN,
}

_BASHRC = """\
for _f in \\
  "/opt/homebrew/share/google-cloud-sdk/path.bash.inc" \\
  "/opt/homebrew/share/google-cloud-sdk/completion.bash.inc" \\
  "/usr/lib/google-cloud-sdk/path.bash.inc" \\
  "/usr/lib/google-cloud-sdk/completion.bash.inc"; do
  [ -f "$_f" ] && source "$_f"
done
unset _f
"""

_ALIASES = r"""alias gcp='gcloud config configurations activate default'

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
"""


@dataclass(frozen=True)
class Gcloud:
    name: str = "gcloud"

    def applies_to(self, env: Environment) -> bool:
        return env.os in _SETUP_BY_OS

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP_BY_OS[env.os],
            bashrc=_BASHRC,
            alias=_ALIASES,
        )
