from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_JAVA_SETUP_DEBIAN = """\
install_packages ca-certificates curl gnupg
add_repo apt adoptium "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb trixie main" "https://packages.adoptium.net/artifactory/api/gpg/key/public"
update_pkg_index
install_package temurin-17-jdk
"""

_SETUP_BY_OS: dict[OS, str] = {
    OS.MACOS: "install_package openjdk@17\n",
    OS.CACHYOS: "install_package jdk17-openjdk\n",
    OS.DEBIAN: _JAVA_SETUP_DEBIAN,
}

_JAVA_HOME = {
    OS.MACOS: "$(brew --prefix openjdk@17)/libexec/openjdk.jdk/Contents/Home",
    OS.CACHYOS: "/usr/lib/jvm/java-17-openjdk",
    OS.DEBIAN: "/usr/lib/jvm/temurin-17-jdk-$(dpkg --print-architecture)",
}


@dataclass(frozen=True)
class Java:
    name: str = "java"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP_BY_OS[env.os],
            bashrc=f'JAVA_HOME="{_JAVA_HOME[env.os]}"\nexport JAVA_HOME\nexport PATH="$JAVA_HOME/bin:$PATH"\n',
        )
