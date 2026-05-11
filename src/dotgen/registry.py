from dotgen.component import Component
from dotgen.components.aws import Aws
from dotgen.components.bash_base import BashBase
from dotgen.components.claude_code import ClaudeCode
from dotgen.components.core_utils import CoreUtils
from dotgen.components.dotfiles_deploy import DotfilesDeploy
from dotgen.components.fonts import Fonts
from dotgen.components.gcloud import Gcloud
from dotgen.components.gh import Gh
from dotgen.components.ghostty import Ghostty
from dotgen.components.git_setup import GitSetup
from dotgen.components.git_signing import GitSigning
from dotgen.components.go_lang import GoLang
from dotgen.components.helix import Helix
from dotgen.components.kubectl import Kubectl
from dotgen.components.node_fnm import NodeFnm
from dotgen.components.python_tools import PythonTools
from dotgen.components.rust import Rust
from dotgen.components.starship import Starship
from dotgen.components.zed import Zed
from dotgen.components.zoxide import Zoxide
from dotgen.environment import Environment
from dotgen.types import OS, PkgMgr

_SHARED: tuple[Component, ...] = (
    BashBase(),
    CoreUtils(),
    Helix(),
    Starship(),
    Zoxide(),
    Kubectl(),
    PythonTools(),
    ClaudeCode(),
    Gh(),
    GitSigning(),
    Rust(),
    NodeFnm(),
    GoLang(),
    Gcloud(),
    Aws(),
    Fonts(),
)

_MACOS_GUI: tuple[Component, ...] = (Ghostty(), Zed())

# GitSetup wires `gh auth git-credential` as the github HTTPS credential
# helper, so it must run after Gh() (in _SHARED) has put gh on PATH.
_LAST: tuple[Component, ...] = (GitSetup(), DotfilesDeploy())

ENVIRONMENTS: dict[str, Environment] = {
    "debian": Environment(
        "debian",
        OS.DEBIAN,
        PkgMgr.APT,
        components=_SHARED + _LAST,
    ),
    "macos": Environment(
        "macos",
        OS.MACOS,
        PkgMgr.BREW,
        components=_SHARED + _MACOS_GUI + _LAST,
    ),
}
