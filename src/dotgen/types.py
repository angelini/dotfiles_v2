from enum import StrEnum


class OS(StrEnum):
    CACHYOS = "cachyos"
    DEBIAN = "debian"
    MACOS = "macos"

    @property
    def is_linux(self) -> bool:
        return self in (OS.CACHYOS, OS.DEBIAN)


class PkgMgr(StrEnum):
    APT = "apt"
    BREW = "brew"
    PACMAN = "pacman"


class EnvironmentRole(StrEnum):
    WORKSTATION = "workstation"
    SERVER = "server"
    CONTAINER = "container"


class Arch(StrEnum):
    X86_64 = "x86_64"
    ARM64 = "arm64"
