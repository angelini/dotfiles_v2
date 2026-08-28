from dotgen.component import Component
from dotgen.components.aws import Aws
from dotgen.components.bash_base import BashBase
from dotgen.components.claude_code import ClaudeCode
from dotgen.components.core_utils import CoreUtils
from dotgen.components.docker import Docker
from dotgen.components.doppler import Doppler
from dotgen.components.dotfiles_deploy import DotfilesDeploy
from dotgen.components.fonts import Fonts
from dotgen.components.fzf_bash_history import FzfBashHistory
from dotgen.components.gcloud import Gcloud
from dotgen.components.gh import Gh
from dotgen.components.ghostty import Ghostty
from dotgen.components.git_setup import GitSetup
from dotgen.components.git_signing import GitSigning
from dotgen.components.go_lang import GoLang
from dotgen.components.helix import Helix
from dotgen.components.herdr import Herdr
from dotgen.components.kubectl import Kubectl
from dotgen.components.mosh import Mosh
from dotgen.components.node_fnm import NodeFnm
from dotgen.components.npm_config import NpmConfig
from dotgen.components.orbstack import OrbStack
from dotgen.components.pi_agent import PiAgent
from dotgen.components.postgres import Postgres
from dotgen.components.python_tools import PythonTools
from dotgen.components.rust import Rust
from dotgen.components.shellcheck import Shellcheck
from dotgen.components.starship import Starship
from dotgen.components.taplo import Taplo
from dotgen.components.terraform import Terraform
from dotgen.components.tmux import Tmux
from dotgen.components.tmuxinator import Tmuxinator
from dotgen.components.zed import Zed
from dotgen.components.zig import Zig
from dotgen.components.zoxide import Zoxide
from dotgen.environment import Environment
from dotgen.types import OS, PkgMgr

_SHARED: tuple[Component, ...] = (
    BashBase(),
    CoreUtils(),
    FzfBashHistory(),
    Tmux(),
    Mosh(),
    Herdr(),
    Helix(),
    Starship(),
    Shellcheck(),
    Zoxide(),
    Kubectl(),
    PythonTools(),
    ClaudeCode(),
    Gh(),
    GitSigning(),
    Rust(),
    Taplo(),
    Terraform(),
    Zig(),
    NodeFnm(),
    NpmConfig(),
    PiAgent(),
    Postgres(),
    GoLang(),
    Gcloud(),
    Aws(),
    Doppler(),
    Fonts(),
)

_DEBIAN_FULL: tuple[Component, ...] = (Tmuxinator(), Docker())

_MACOS_GUI: tuple[Component, ...] = (Ghostty(), Zed(), OrbStack())

_DOCKER_SKIP = {
    "fonts",
    "git_signing",
    "aws",
    "gcloud",
    "rust",
    "taplo",
    "terraform",
    "zig",
    "go_lang",
    "python_tools",
    "claude_code",
    "postgres",
    "doppler",
    "tmux",
    "mosh",
    "herdr",
}

# GitSetup depends on Gh
_LAST: tuple[Component, ...] = (GitSetup(), DotfilesDeploy())

ENVIRONMENTS: dict[str, Environment] = {
    "debian": Environment(
        "debian",
        OS.DEBIAN,
        PkgMgr.APT,
        components=_SHARED + _DEBIAN_FULL + _LAST,
    ),
    "debian-docker": Environment(
        "debian-docker",
        OS.DEBIAN,
        PkgMgr.APT,
        components=tuple(c for c in _SHARED if c.name not in _DOCKER_SKIP) + _LAST,
    ),
    "macos": Environment(
        "macos",
        OS.MACOS,
        PkgMgr.BREW,
        components=_SHARED + _MACOS_GUI + _LAST,
    ),
}
