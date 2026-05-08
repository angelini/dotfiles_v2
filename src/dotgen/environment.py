from dataclasses import dataclass

from dotgen.component import Component
from dotgen.components.aws import Aws
from dotgen.components.bash_base import BashBase
from dotgen.components.claude_code import ClaudeCode
from dotgen.components.core_utils import CoreUtils
from dotgen.components.dotfiles_deploy import DotfilesDeploy
from dotgen.components.gcloud import Gcloud
from dotgen.components.gh import Gh
from dotgen.components.ghostty import Ghostty
from dotgen.components.git_setup import GitSetup
from dotgen.components.github_ssh import GitHubSsh
from dotgen.components.go_lang import GoLang
from dotgen.components.helix import Helix
from dotgen.components.kubectl import Kubectl
from dotgen.components.node_fnm import NodeFnm
from dotgen.components.python_tools import PythonTools
from dotgen.components.rust import Rust
from dotgen.components.starship import Starship
from dotgen.components.zed import Zed
from dotgen.components.zoxide import Zoxide
from dotgen.types import OS, PkgMgr


@dataclass(frozen=True)
class Environment:
    name: str
    os: OS
    pkg_mgr: PkgMgr
    components: tuple[Component, ...] = ()


_BASE: tuple[Component, ...] = (
    BashBase(),
    CoreUtils(),
    GitSetup(),
    GitHubSsh(),
    Helix(),
)

_SHARED: tuple[Component, ...] = _BASE + (
    Starship(),
    Zoxide(),
    Kubectl(),
    PythonTools(),
    ClaudeCode(),
    Gh(),
)

_FULL_ADDONS: tuple[Component, ...] = (
    Rust(),
    NodeFnm(),
    GoLang(),
    Gcloud(),
    Aws(),
    Zed(),
)

_LAST: tuple[Component, ...] = (DotfilesDeploy(),)

ENVIRONMENTS: dict[str, Environment] = {
    "debian": Environment("debian", OS.DEBIAN, PkgMgr.APT, components=_SHARED + _LAST),
    "fedora": Environment(
        "fedora", OS.FEDORA, PkgMgr.DNF, components=_SHARED + _FULL_ADDONS + _LAST
    ),
    "macos": Environment(
        "macos",
        OS.MACOS,
        PkgMgr.BREW,
        components=_SHARED + _FULL_ADDONS + (Ghostty(),) + _LAST,
    ),
}
