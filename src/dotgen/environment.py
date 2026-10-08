from dataclasses import dataclass

from dotgen.component import Component
from dotgen.types import OS, EnvironmentRole, PkgMgr


@dataclass(frozen=True)
class Environment:
    name: str
    os: OS
    pkg_mgr: PkgMgr
    role: EnvironmentRole
    components: tuple[Component, ...] = ()
