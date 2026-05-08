from enum import StrEnum


class OS(StrEnum):
    DEBIAN = "debian"
    FEDORA = "fedora"
    MACOS = "macos"


class PkgMgr(StrEnum):
    APT = "apt"
    DNF = "dnf"
    BREW = "brew"


class Arch(StrEnum):
    X86_64 = "x86_64"
    ARM64 = "arm64"
