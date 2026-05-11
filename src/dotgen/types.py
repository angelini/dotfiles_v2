from enum import StrEnum


class OS(StrEnum):
    DEBIAN = "debian"
    MACOS = "macos"


class PkgMgr(StrEnum):
    APT = "apt"
    BREW = "brew"


class Arch(StrEnum):
    X86_64 = "x86_64"
    ARM64 = "arm64"
