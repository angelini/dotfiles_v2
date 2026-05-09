from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_FEDORA_REPO = r"""[google-cloud-cli]
name=Google Cloud CLI
baseurl=https://packages.cloud.google.com/yum/repos/cloud-sdk-el9-\$basearch
enabled=1
gpgcheck=1
repo_gpgcheck=0
gpgkey=https://packages.cloud.google.com/yum/doc/rpm-package-key.gpg
"""

_SETUP_MACOS = "install_cask google-cloud-sdk\n"

_SETUP_FEDORA = f'add_repo dnf google-cloud-cli "{_FEDORA_REPO}"\ninstall_package google-cloud-cli\n'

_SETUP_BY_OS: dict[OS, str] = {
    OS.MACOS: _SETUP_MACOS,
    OS.FEDORA: _SETUP_FEDORA,
}

_BASHRC = """\
for _f in \\
  "/opt/homebrew/share/google-cloud-sdk/path.bash.inc" \\
  "/opt/homebrew/share/google-cloud-sdk/completion.bash.inc" \\
  "/usr/lib64/google-cloud-sdk/path.bash.inc" \\
  "/usr/lib64/google-cloud-sdk/completion.bash.inc"; do
  [ -f "$_f" ] && source "$_f"
done
unset _f
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
        )
