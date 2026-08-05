from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_DEBIAN_REPO = "deb [signed-by=/etc/apt/keyrings/doppler-cli.gpg] https://packages.doppler.com/public/cli/deb/debian any-version main"
_DEBIAN_KEY_URL = "https://packages.doppler.com/public/cli/gpg.DE2A7741A397C129.key"

_SETUP_DEBIAN = f"""\
install_packages apt-transport-https ca-certificates curl gnupg
add_repo apt doppler-cli "{_DEBIAN_REPO}" "{_DEBIAN_KEY_URL}"
update_pkg_index
install_package doppler
"""

_SETUP_BY_OS: dict[OS, str] = {
    OS.DEBIAN: _SETUP_DEBIAN,
    OS.MACOS: "install_package gnupg\nif ! bin_exists doppler; then\n  install_package dopplerhq/cli/doppler\nfi\n",
}


@dataclass(frozen=True)
class Doppler:
    name: str = "doppler"

    def applies_to(self, env: Environment) -> bool:
        return env.name in {"debian", "macos"}

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP_BY_OS[env.os])
