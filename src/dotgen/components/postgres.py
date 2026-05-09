from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_PG_VERSION = "18"

_SETUP_MACOS = f"install_package postgresql@{_PG_VERSION}\n"

_DEB_LINE = "deb [signed-by=/etc/apt/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt ${codename}-pgdg main"
_DEB_KEY_URL = "https://www.postgresql.org/media/keys/ACCC4CF8.asc"

_SETUP_DEBIAN = (
    r'codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"' + "\n" + f'add_repo apt pgdg "{_DEB_LINE}" "{_DEB_KEY_URL}"\n' + "update_pkg_index\n" + f"install_package postgresql-{_PG_VERSION}\n"
)

_FEDORA_REPO = f"""[pgdg{_PG_VERSION}]
name=PostgreSQL {_PG_VERSION} for Fedora $releasever - $basearch
baseurl=https://download.postgresql.org/pub/repos/yum/{_PG_VERSION}/fedora/fedora-$releasever-$basearch
enabled=1
gpgcheck=1
gpgkey=https://download.postgresql.org/pub/repos/yum/keys/PGDG-RPM-GPG-KEY-FEDORA
"""

_SETUP_FEDORA = f"add_repo dnf pgdg{_PG_VERSION} '{_FEDORA_REPO.rstrip()}'\ninstall_package postgresql{_PG_VERSION}-server\n"

_SETUP_BY_OS: dict[OS, str] = {
    OS.MACOS: _SETUP_MACOS,
    OS.DEBIAN: _SETUP_DEBIAN,
    OS.FEDORA: _SETUP_FEDORA,
}

_BASHRC_BY_OS: dict[OS, str] = {
    OS.MACOS: f'export PATH="/opt/homebrew/opt/postgresql@{_PG_VERSION}/bin:$PATH"\n',
    OS.DEBIAN: f'export PATH="/usr/lib/postgresql/{_PG_VERSION}/bin:$PATH"\n',
    OS.FEDORA: f'export PATH="/usr/pgsql-{_PG_VERSION}/bin:$PATH"\n',
}


@dataclass(frozen=True)
class Postgres:
    name: str = "postgres"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP_BY_OS[env.os],
            bashrc=_BASHRC_BY_OS[env.os],
        )
