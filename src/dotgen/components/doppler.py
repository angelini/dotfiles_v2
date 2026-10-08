from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_DEBIAN_REPO = "deb [signed-by=/etc/apt/keyrings/doppler-cli.gpg] https://packages.doppler.com/public/cli/deb/debian any-version main"
_DEBIAN_KEY_URL = "https://packages.doppler.com/public/cli/gpg.DE2A7741A397C129.key"
_VERSION = "3.76.5"
_RELEASE_BASE = f"https://github.com/DopplerHQ/cli/releases/download/{_VERSION}"
_SHA256_LINUX = {
    "amd64": "1b2f412d984920d665daf233ab6c15b364df9339b5c5b5224d5e8ee4e0a70154",
    "arm64": "567f051c4c334b79a37ee44c9373671c451dd8a4945ed49288a8f3fd0b73ec89",
}

_SETUP_DEBIAN = f"""\
install_packages apt-transport-https ca-certificates curl gnupg
add_repo apt doppler-cli "{_DEBIAN_REPO}" "{_DEBIAN_KEY_URL}"
update_pkg_index
install_package doppler
"""

_SETUP_CACHYOS = f"""\
case "$(detect_arch)" in
  x86_64) doppler_arch=amd64; doppler_checksum={_SHA256_LINUX["amd64"]} ;;
  aarch64|arm64) doppler_arch=arm64; doppler_checksum={_SHA256_LINUX["arm64"]} ;;
  *) error "unsupported arch for Doppler: $(detect_arch)"; exit 1 ;;
esac
download_tar_bin_sha256 doppler \
  "{_RELEASE_BASE}/doppler_{_VERSION}_linux_${{doppler_arch}}.tar.gz" \
  "$doppler_checksum" doppler "v{_VERSION}" --version
unset doppler_arch doppler_checksum
remove_packages doppler-cli-bin
"""

_SETUP_BY_OS: dict[OS, str] = {
    OS.CACHYOS: _SETUP_CACHYOS,
    OS.DEBIAN: _SETUP_DEBIAN,
    OS.MACOS: "install_package gnupg\nif ! bin_exists doppler; then\n  install_package dopplerhq/cli/doppler\nfi\n",
}


@dataclass(frozen=True)
class Doppler:
    name: str = "doppler"

    def applies_to(self, env: Environment) -> bool:
        return env.name != "debian-docker" and env.os in _SETUP_BY_OS

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP_BY_OS[env.os])
