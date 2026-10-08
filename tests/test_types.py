from dotgen.registry import ENVIRONMENTS
from dotgen.types import OS, EnvironmentRole, PkgMgr


def test_linux_family_classification_is_explicit() -> None:
    assert OS.CACHYOS.is_linux
    assert OS.DEBIAN.is_linux
    assert not OS.MACOS.is_linux


def test_cachyos_platform_values() -> None:
    assert OS.CACHYOS.value == "cachyos"
    assert PkgMgr.PACMAN.value == "pacman"


def test_registered_environments_have_explicit_roles() -> None:
    assert {name: env.role for name, env in ENVIRONMENTS.items()} == {
        "debian": EnvironmentRole.SERVER,
        "debian-docker": EnvironmentRole.CONTAINER,
        "macos": EnvironmentRole.WORKSTATION,
        "cachyos": EnvironmentRole.WORKSTATION,
    }


def test_cachyos_environment_is_registered_with_pacman() -> None:
    assert ENVIRONMENTS["cachyos"].os is OS.CACHYOS
    assert ENVIRONMENTS["cachyos"].pkg_mgr is PkgMgr.PACMAN
