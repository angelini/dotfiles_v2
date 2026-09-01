import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

from dotgen.component import Component
from dotgen.components import agent_config as agent_config_module
from dotgen.components.agent_config import _agent_config_root, managed_settings, pi_models  # pyright: ignore[reportPrivateUsage]
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
from dotgen.components.pi_agent import _PI_PACKAGES, SANDBOX_HOME_POLICY, PiAgent, _pi_angelini_root  # pyright: ignore[reportPrivateUsage]
from dotgen.components.postgres import Postgres
from dotgen.components.python_tools import PythonTools
from dotgen.components.rust import Rust
from dotgen.components.starship import Starship
from dotgen.components.taplo import Taplo
from dotgen.components.terraform import Terraform
from dotgen.components.tmux import Tmux
from dotgen.components.tmuxinator import Tmuxinator
from dotgen.components.zed import Zed
from dotgen.components.zig import Zig
from dotgen.components.zoxide import Zoxide
from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.registry import ENVIRONMENTS
from dotgen.render import _vendor_dir  # pyright: ignore[reportPrivateUsage]
from dotgen.vendor import BUILD_ARTIFACTS, GIT_ARTIFACTS, NODE_ARTIFACTS, PY_ARTIFACTS, VendorDir


@pytest.fixture(params=list(ENVIRONMENTS.values()), ids=list(ENVIRONMENTS))
def env(request: pytest.FixtureRequest) -> Environment:
    return request.param


@pytest.mark.parametrize(
    "cls",
    [
        BashBase,
        CoreUtils,
        FzfBashHistory,
        Tmux,
        Mosh,
        Tmuxinator,
        GitSetup,
        Helix,
        Herdr,
        Starship,
        Zoxide,
        Kubectl,
        ClaudeCode,
        PythonTools,
        Gh,
        GitSigning,
        NpmConfig,
        PiAgent,
    ],
)
def test_component_render_returns_fragment(env: Environment, cls: type[Component]) -> None:
    frag: Fragment = cls().render(env)
    assert isinstance(frag, Fragment)


@pytest.mark.parametrize("cls", [Rust, Taplo, Terraform, Zig, NodeFnm, GoLang, Gcloud, Aws, Doppler, Fonts, Zed, OrbStack, PiAgent])
def test_addon_component_renders_for_supported_oses(cls: type[Component]) -> None:
    for env_name in ("macos", "debian", "debian-docker"):
        env = ENVIRONMENTS[env_name]
        comp = cls()
        if comp.applies_to(env):
            assert isinstance(comp.render(env), Fragment)


def test_taplo_installs_for_normal_environments() -> None:
    debian = Taplo().render(ENVIRONMENTS["debian"]).setup
    macos = Taplo().render(ENVIRONMENTS["macos"]).setup
    assert "taplo-linux-${arch}.gz" in debian
    assert "taplo-darwin-${arch}.gz" in macos
    assert "sha256_file" in debian
    assert "sha256_file" in macos
    assert '"0.10.0" --version' in debian
    assert '"0.10.0" --version' in macos
    assert "install_package" not in macos
    assert not Taplo().applies_to(ENVIRONMENTS["debian-docker"])


def test_terraform_tools_install_for_normal_environments() -> None:
    terraform = Terraform()
    assert terraform.applies_to(ENVIRONMENTS["debian"])
    assert terraform.applies_to(ENVIRONMENTS["macos"])
    assert not terraform.applies_to(ENVIRONMENTS["debian-docker"])

    for env_name in ("debian", "macos"):
        names = [component.name for component in ENVIRONMENTS[env_name].components]
        assert names.count("terraform") == 1
    assert "terraform" not in [component.name for component in ENVIRONMENTS["debian-docker"].components]

    debian = terraform.render(ENVIRONMENTS["debian"]).setup
    assert "https://apt.releases.hashicorp.com trixie main" in debian
    assert "https://apt.releases.hashicorp.com/gpg" in debian
    assert debian.index("update_pkg_index") < debian.index("install_package terraform")
    assert "terragrunt/releases/download/v0.96.1/terragrunt_linux_${arch}" in debian
    assert "513eff2f87e2f5ec84369cc0f9d6c6766b43ca765fec4a3ac3598b933dc3218f" in debian
    assert "5cf6006c99b4d05e03eea1375cf8a591ade8b06a40e804b0b73f89f7589347c3" in debian
    assert '"$checksum" "v0.96.1" --version' in debian

    macos = terraform.render(ENVIRONMENTS["macos"]).setup
    assert "add_repo tap hashicorp/tap" in macos
    assert "install_package hashicorp/tap/terraform" in macos
    assert "install_package terragrunt" in macos


def test_zig_installs_for_normal_environments() -> None:
    debian = Zig().render(ENVIRONMENTS["debian"])
    macos = Zig().render(ENVIRONMENTS["macos"])
    assert "zig-${arch}-linux-0.16.0.tar.xz" in debian.setup
    assert "zig-${arch}-macos-0.16.0.tar.xz" in macos.setup
    assert "sha256_file" in debian.setup
    assert "sha256_file" in macos.setup
    assert 'export PATH="$HOME/.local/share/zig:$PATH"' in debian.bashrc
    assert macos.bashrc == debian.bashrc
    assert "install_package zig" not in macos.setup
    assert not Zig().applies_to(ENVIRONMENTS["debian-docker"])


def test_rust_installs_target_and_analyzer() -> None:
    setup = Rust().render(ENVIRONMENTS["debian"]).setup
    assert "install_script rustup https://sh.rustup.rs" in setup
    assert '[ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env"' in setup
    assert "rustup target add wasm32-wasip2" in setup
    assert "rustup component add rust-analyzer" in setup


def _run_tool_setup(tmp_path: Path, setup: str, prelude: str) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "tool-setup.sh"
    script.write_text("set -euo pipefail\n" + prelude + setup)
    return subprocess.run(["bash", str(script)], env={**os.environ, "HOME": str(tmp_path / "home")}, capture_output=True, text=True)


def test_taplo_setup_reuses_verified_binary_without_downloading(tmp_path: Path) -> None:
    binary = tmp_path / "home" / "bin" / "taplo"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/usr/bin/env bash\nprintf 'taplo 0.10.0\\n'\n")
    binary.chmod(0o755)
    marker = tmp_path / "downloaded"
    prelude = f"""\
detect_arch() {{ printf 'x86_64\\n'; }}
sha256_file() {{ printf 'dad2faf6377d2daa4f4fabf459fe7ccfb98a5448f0d4bca8270ca9acb0409bfe\\n'; }}
bin_version_matches() {{ local bin="$1" expected="$2"; shift 2; "$bin" "$@" | grep -qw "$expected"; }}
ensure_dir() {{ mkdir -p "$1"; }}
error() {{ printf '%s\\n' "$*" >&2; }}
curl() {{ touch {shlex.quote(str(marker))}; return 99; }}
"""

    result = _run_tool_setup(tmp_path, Taplo().render(ENVIRONMENTS["debian"]).setup, prelude)

    assert result.returncode == 0, result.stderr
    assert not marker.exists()


def test_zig_setup_reuses_matching_installation_without_downloading(tmp_path: Path) -> None:
    binary = tmp_path / "home" / ".local" / "share" / "zig" / "zig"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/usr/bin/env bash\nprintf '0.16.0\\n'\n")
    binary.chmod(0o755)
    marker = tmp_path / "downloaded"
    prelude = f"""\
install_package() {{ :; }}
detect_arch() {{ printf 'x86_64\\n'; }}
ensure_dir() {{ mkdir -p "$1"; }}
error() {{ printf '%s\\n' "$*" >&2; }}
curl() {{ touch {shlex.quote(str(marker))}; return 99; }}
"""

    result = _run_tool_setup(tmp_path, Zig().render(ENVIRONMENTS["debian"]).setup, prelude)

    assert result.returncode == 0, result.stderr
    assert not marker.exists()


def test_tool_setups_reject_unsafe_managed_destinations(tmp_path: Path) -> None:
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()
    taplo = home / "bin" / "taplo"
    taplo.parent.mkdir(parents=True)
    taplo.symlink_to(target)
    prelude = """\
install_package() { :; }
detect_arch() { printf 'x86_64\\n'; }
error() { printf '%s\\n' "$*" >&2; }
"""

    taplo_result = _run_tool_setup(tmp_path, Taplo().render(ENVIRONMENTS["debian"]).setup, prelude)

    assert taplo_result.returncode != 0
    assert "unsafe Taplo binary destination" in taplo_result.stderr

    taplo.unlink()
    zig = home / ".local" / "share" / "zig"
    zig.parent.mkdir(parents=True)
    zig.symlink_to(target, target_is_directory=True)

    zig_result = _run_tool_setup(tmp_path, Zig().render(ENVIRONMENTS["debian"]).setup, prelude)

    assert zig_result.returncode != 0
    assert "unsafe Zig installation destination" in zig_result.stderr


def test_bash_base_l_alias_uses_eza() -> None:
    expected = "alias l='eza --long --all --group-directories-first --git'"
    for environment in ENVIRONMENTS.values():
        assert expected in BashBase().render(environment).alias


def test_bash_base_git_aliases() -> None:
    aliases = BashBase().render(ENVIRONMENTS["debian"]).alias.splitlines()
    expected = {
        "alias gs='git status'",
        "alias gc='git checkout'",
        "alias ga='git commit --amend --no-edit'",
        "alias gpo='git push origin $(git rev-parse --abbrev-ref HEAD)'",
        "alias gpfo='git push origin +$(git rev-parse --abbrev-ref HEAD)'",
        ("alias gl=\"git log --graph --pretty=format:'%Cred%h%Creset %Creset%Cblue%an%Creset %s %Cgreen(%cr)%Cred%d%Creset' --abbrev-commit --date=relative --max-count=25\""),
    }
    assert expected <= set(aliases)


def test_bash_base_macos_changes_shell_and_loads_orbstack() -> None:
    macos = BashBase().render(ENVIRONMENTS["macos"])
    assert 'sudo chsh -s /opt/homebrew/bin/bash "$(whoami)"' in macos.setup
    assert 'eval "$(/opt/homebrew/bin/brew shellenv)"' in macos.bashrc
    assert '[ -r "$HOME/.orbstack/shell/init.bash" ] && source "$HOME/.orbstack/shell/init.bash"' in macos.bashrc
    assert ".orbstack/shell/init.bash" not in BashBase().render(ENVIRONMENTS["debian"]).bashrc
    assert "brew shellenv" not in BashBase().render(ENVIRONMENTS["debian"]).bashrc


def test_bash_base_leaves_history_policy_to_dedicated_component_and_preserves_title_status() -> None:
    bashrc = BashBase().render(ENVIRONMENTS["macos"]).bashrc
    for forbidden in ("HISTSIZE", "HISTFILESIZE", "HISTCONTROL", "histappend", "history -a"):
        assert forbidden not in bashrc
    assert "set_win_title" in bashrc
    assert 'return "$status"' in bashrc
    assert "PROMPT_COMMAND" in bashrc


def test_fzf_bash_history_owns_persistent_history_policy() -> None:
    bashrc = FzfBashHistory().render(ENVIRONMENTS["macos"]).bashrc
    for expected in ("HISTFILE=~/.bash_history", "HISTSIZE=100000", "HISTFILESIZE=100000", "HISTCONTROL=ignoreboth", "shopt -s histappend", "history -a", "history -n", "fzf --bash"):
        assert expected in bashrc


def test_core_utils_per_os_fd_token() -> None:
    debian = CoreUtils().render(ENVIRONMENTS["debian"]).setup
    macos = CoreUtils().render(ENVIRONMENTS["macos"]).setup
    assert "fd-find" in debian
    assert " fd " in macos and "fd-find" not in macos


def test_core_utils_include_process_monitors() -> None:
    for environment in ENVIRONMENTS.values():
        setup = CoreUtils().render(environment).setup
        assert " htop " in setup
        assert " btop " in setup


def test_core_utils_include_modern_cli_tools() -> None:
    for environment in ENVIRONMENTS.values():
        setup = CoreUtils().render(environment).setup
        assert " git-delta " in setup
        assert " just " in setup
        assert " eza " in setup
        assert " bat " in setup


def test_core_utils_install_protoc_package() -> None:
    debian = CoreUtils().render(ENVIRONMENTS["debian"]).setup
    macos = CoreUtils().render(ENVIRONMENTS["macos"]).setup
    assert "protobuf-compiler" in shlex.split(debian)
    assert "protobuf" in shlex.split(macos)


def test_core_utils_debian_normalizes_binary_names() -> None:
    setup = CoreUtils().render(ENVIRONMENTS["debian"]).setup
    assert "command -v fdfind" in setup
    assert '"$HOME/bin/fd"' in setup
    assert "command -v batcat" in setup
    assert '"$HOME/bin/bat"' in setup
    assert setup.count("link_file ") == 2
    assert "ln -sf" not in setup


def test_git_setup_emits_two_configs() -> None:
    frag = GitSetup().render(ENVIRONMENTS["macos"])
    dests = sorted(c.dest for c in frag.configs)
    assert dests == ["git/gitconfig", "git/gitignore_global"]


def test_git_setup_uses_secret_placeholders() -> None:
    frag = GitSetup().render(ENVIRONMENTS["macos"])
    cfg = next(c for c in frag.configs if c.dest == "git/gitconfig")
    assert "${GIT_USER_NAME}" in cfg.content
    assert "${GIT_USER_EMAIL}" in cfg.content
    assert frag.secrets == frozenset({"GIT_USER_NAME", "GIT_USER_EMAIL"})
    assert "install_config_template " in frag.setup


def test_git_setup_uses_delta_pager() -> None:
    configs = GitSetup().render(ENVIRONMENTS["macos"]).configs
    gitconfig = next(c for c in configs if c.dest == "git/gitconfig").content
    assert "pager = delta" in gitconfig
    assert "diffFilter = delta --color-only" in gitconfig
    assert "light = true" in gitconfig


def test_npm_config_is_secure_and_exact_in_every_environment() -> None:
    expected = "//npm.pkg.github.com/:_authToken=${NPM_TOKEN}\n@qawolf:registry=https://npm.pkg.github.com\n"
    for env in ENVIRONMENTS.values():
        component = NpmConfig()
        assert component.applies_to(env)
        frag = component.render(env)
        assert frag.configs == (ConfigFile(dest="npm/npmrc", content=expected, mode=0o600),)
        assert frag.setup == 'install_config_template "$DIR/config/npm/npmrc" "$HOME/.npmrc" \'NPM_TOKEN\' 0600\n'
        assert frag.secrets == frozenset({"NPM_TOKEN"})


def test_git_setup_signs_with_ssh_key() -> None:
    cfg = next(c for c in GitSetup().render(ENVIRONMENTS["macos"]).configs if c.dest == "git/gitconfig").content
    assert "format = ssh" in cfg
    assert "signingkey = ~/.ssh/id_signing.pub" in cfg
    assert "gpgsign = true" in cfg


def test_git_setup_ignores_local_agent_state() -> None:
    cfg = next(c for c in GitSetup().render(ENVIRONMENTS["macos"]).configs if c.dest == "git/gitignore_global").content
    for pattern in (".pi/APPEND_SYSTEM.md", ".pi/settings.json", ".pi-lens/", ".pi-subagents/", "**/.claude/settings.local.json"):
        assert pattern in cfg


def test_fonts_per_os_packages() -> None:
    macos = Fonts().render(ENVIRONMENTS["macos"]).setup
    debian = Fonts().render(ENVIRONMENTS["debian"]).setup
    assert 'if [ ! -f "$HOME/Library/Fonts/Ubuntu-Regular.ttf" ]' in macos
    assert 'if [ ! -f "$HOME/Library/Fonts/UbuntuMonoNerdFont-Regular.ttf" ]' in macos
    assert "font-ubuntu" in macos and "font-ubuntu-mono-nerd-font" in macos
    assert "fontconfig" in debian
    assert Fonts().applies_to(ENVIRONMENTS["debian"])


def test_git_signing_uploads_via_gh() -> None:
    setup = GitSigning().render(ENVIRONMENTS["macos"]).setup
    assert "ssh-keygen -t ed25519" in setup
    assert "id_signing" in setup
    assert "gh ssh-key add" in setup
    assert "--type signing" in setup


def test_helix_emits_config_and_editor_env(env: Environment) -> None:
    frag = Helix().render(env)
    cfg = next(c for c in frag.configs if c.dest == "helix/config.toml").content
    assert 'theme = "base16_default_light"' in cfg
    assert "true-color = true" in cfg
    assert 'normal = "block"' in cfg
    assert 'select = "underline"' in cfg
    assert "[editor.file-picker]" in cfg
    assert "hidden = false" in cfg
    assert "EDITOR=hx" in frag.bashrc


_LEGACY_HERD_AGENT = r"""#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ] || [[ "$1" = -* ]]; then
  printf 'usage: herd-agent <ssh-config-host>\n' >&2
  exit 2
fi

herdr_bin="$HOME/.local/bin/herdr"
if [ ! -f "$herdr_bin" ] || [ ! -x "$herdr_bin" ]; then
  printf 'herd-agent: managed Herdr binary is missing or invalid: %s\n' "$herdr_bin" >&2
  exit 1
fi

exec "$herdr_bin" --remote "$1"
"""


def test_herdr_is_pinned_managed_and_excludes_docker() -> None:
    herdr = Herdr()
    assert herdr.applies_to(ENVIRONMENTS["debian"])
    assert herdr.applies_to(ENVIRONMENTS["macos"])
    assert not herdr.applies_to(ENVIRONMENTS["debian-docker"])

    expected_assets = {
        "debian": (
            "herdr-linux-${arch}",
            "976150a14d490c94b243ea2e1a7eb2dfb67f12e36b182db90936f6728e6aecf4",
            "f55610658e1c2e0d2aaef730b4b2ab885f7f8ba00285ab372bfb14f2e3d5b40d",
        ),
        "macos": (
            "herdr-macos-${arch}",
            "ab50262c8190cd7aa9056d249d255c08c328c3e8716de9cfa29db4f131b8e2c1",
            "a5d4f4d504d8b309c91f811050559300faba31258425f53c50852fc96f6ae574",
        ),
    }
    for env_name, (asset, x86_sha, arm_sha) in expected_assets.items():
        fragment = herdr.render(ENVIRONMENTS[env_name])
        assert f"https://github.com/herdrdev/herdr/releases/download/v0.8.2/{asset}" in fragment.setup
        assert f"x86_64) arch=x86_64; checksum={x86_sha}" in fragment.setup
        assert f"aarch64|arm64) arch=aarch64; checksum={arm_sha}" in fragment.setup
        assert "download_bin_sha256 herdr" in fragment.setup
        assert '"0.8.2" --version' in fragment.setup
        assert 'remote_bin="$HOME/.local/bin/herdr"' in fragment.setup
        assert 'error "unsafe Herdr remote binary destination: $remote_bin"' in fragment.setup
        assert 'link_file "$HOME/bin/herdr" "$remote_bin"' in fragment.setup
        assert 'error "failed to publish Herdr remote binary: $remote_bin"' in fragment.setup
        assert '"$remote_bin" plugin install "persiyanov/herdr-reviewr" --ref "v0.36.0" --yes' in fragment.setup
        assert (
            'install_config "$DIR/config/herdr/plugins/config/persiyanov.reviewr/config.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/plugins/config/persiyanov.reviewr/config.toml"' in fragment.setup
        )
        assert "alexarthurs/herdr-sidebar" not in fragment.setup
        assert '"$HOME/.local/bin/herd-agent"' in fragment.setup
        assert "requires manual remediation" in fragment.setup

    debian = herdr.render(ENVIRONMENTS["debian"])
    debian_configs = {config.dest: config for config in debian.configs}
    assert set(debian_configs) == {"herdr/config.toml", "herdr/plugins/config/persiyanov.reviewr/config.toml"}
    assert 'name = "catppuccin-latte"' in debian_configs["herdr/config.toml"].content
    assert "[remote]\nmanage_ssh_config = true" in debian_configs["herdr/config.toml"].content
    assert not any("herd-" in dest for dest in debian_configs)
    assert 'install_config "$DIR/config/herdr/config.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/config.toml"' in debian.setup
    assert "herd-local" not in debian.setup and "herd-remote" not in debian.setup

    macos = herdr.render(ENVIRONMENTS["macos"])
    macos_configs = {config.dest: config for config in macos.configs}
    assert set(macos_configs) == {
        "herdr/herd-local",
        "herdr/herd-remote",
        "herdr/local.toml",
        "herdr/remote.toml",
        "herdr/plugins/config/persiyanov.reviewr/config.toml",
    }
    assert macos_configs["herdr/herd-local"].mode == 0o755
    assert macos_configs["herdr/herd-remote"].mode == 0o755
    assert 'name = "catppuccin-latte"' in macos_configs["herdr/local.toml"].content
    assert "[remote]" not in macos_configs["herdr/local.toml"].content
    assert 'name = "rose-pine-dawn"' in macos_configs["herdr/remote.toml"].content
    assert "[remote]\nmanage_ssh_config = true" in macos_configs["herdr/remote.toml"].content
    assert "herdr/config.toml" not in macos_configs and "herdr/herd-agent" not in macos_configs
    for source, destination in (
        ("local.toml", "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/local.toml"),
        ("remote.toml", "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/remote.toml"),
    ):
        assert f'install_config "$DIR/config/herdr/{source}" "{destination}"' in macos.setup
    for launcher in ("herd-local", "herd-remote"):
        assert f'install -m 0755 "$DIR/config/herdr/{launcher}" "$HOME/.local/bin/{launcher}"' in macos.setup
    assert "brew list --cask --versions supacode" in macos.setup
    assert "brew uninstall --cask supacode" in macos.setup

    for env_name in ("debian", "macos"):
        assert [component.name for component in ENVIRONMENTS[env_name].components].count("herdr") == 1
    assert "herdr" not in [component.name for component in ENVIRONMENTS["debian-docker"].components]


@pytest.mark.parametrize("destination_kind", ["directory", "fifo"])
def test_herdr_setup_rejects_unsafe_remote_binary_destination(tmp_path: Path, destination_kind: str) -> None:
    home = tmp_path / "home"
    remote_bin = home / ".local/bin/herdr"
    remote_bin.parent.mkdir(parents=True)
    if destination_kind == "directory":
        remote_bin.mkdir()
    else:
        os.mkfifo(remote_bin)
    config_touched = tmp_path / "config-touched"
    setup = Herdr().render(ENVIRONMENTS["macos"]).setup
    script = tmp_path / "setup.sh"
    script.write_text(
        f"""set -euo pipefail
error() {{ printf '%s\\n' "$*" >&2; }}
detect_arch() {{ printf 'arm64\\n'; }}
download_bin_sha256() {{ :; }}
ensure_dir() {{ mkdir -p "$1"; }}
link_file() {{ ln -sf "$1" "$2"; }}
install_config() {{ : > "$CONFIG_TOUCHED"; }}
sha256_file() {{ if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d ' ' -f 1; }}
DIR={shlex.quote(str(tmp_path / "bundle"))}
{setup}
"""
    )

    result = subprocess.run(
        ["bash", str(script)],
        check=False,
        capture_output=True,
        text=True,
        env={"HOME": str(home), "CONFIG_TOUCHED": str(config_touched), "PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 1
    assert "unsafe Herdr remote binary destination" in result.stderr
    assert not config_touched.exists()
    if destination_kind == "directory":
        assert remote_bin.is_dir()
        assert not list(remote_bin.iterdir())
    else:
        assert remote_bin.stat().st_mode & 0o170000 == 0o010000


def _herdr_setup_harness(tmp_path: Path, env_name: str = "macos") -> tuple[Path, Path, dict[str, str]]:
    fragment = Herdr().render(ENVIRONMENTS[env_name])
    home = tmp_path / "home"
    xdg_config = tmp_path / "xdg-config"
    bundle = tmp_path / "bundle"
    for config in fragment.configs:
        path = bundle / "config" / config.dest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(config.content)
        path.chmod(config.mode)
    managed_source = home / "bin/herdr"
    managed_source.parent.mkdir(parents=True)
    managed_source.write_text("#!/usr/bin/env bash\nexit 0\n")
    managed_source.chmod(0o755)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    brew_state = tmp_path / "supacode-installed"
    brew_log = tmp_path / "brew-uninstall.log"
    brew = fake_bin / "brew"
    brew.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$*" = "list --cask --versions supacode" ]; then
  [ -f "$BREW_STATE" ]
elif [ "$*" = "uninstall --cask supacode" ]; then
  printf 'uninstalled\\n' >> "$BREW_LOG"
  rm -- "$BREW_STATE"
else
  exit 2
fi
"""
    )
    brew.chmod(0o755)
    script = tmp_path / "setup.sh"
    script.write_text(
        f"""set -euo pipefail
error() {{ printf '%s\\n' "$*" >&2; }}
detect_arch() {{ printf 'arm64\\n'; }}
download_bin_sha256() {{ :; }}
ensure_dir() {{ mkdir -p "$1"; }}
link_file() {{ ln -sf "$1" "$2"; }}
install_config() {{ mkdir -p "$(dirname "$2")"; install -m 0644 "$1" "$2"; }}
sha256_file() {{ if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d ' ' -f 1; }}
DIR={shlex.quote(str(bundle))}
{fragment.setup}
"""
    )
    env = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(xdg_config),
        "BREW_STATE": str(brew_state),
        "BREW_LOG": str(brew_log),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
    }
    return script, brew_state, env


def test_herdr_macos_upgrade_migration_is_safe_and_idempotent(tmp_path: Path) -> None:
    script, brew_state, env = _herdr_setup_harness(tmp_path)
    home = Path(env["HOME"])
    legacy_helper = home / ".local/bin/herd-agent"
    legacy_helper.parent.mkdir(parents=True)
    legacy_helper.write_text(_LEGACY_HERD_AGENT)
    legacy_config = Path(env["XDG_CONFIG_HOME"]) / "herdr/config.toml"
    legacy_config.parent.mkdir(parents=True)
    debian_config = next(c for c in Herdr().render(ENVIRONMENTS["debian"]).configs if c.dest == "herdr/config.toml")
    legacy_config.write_text(debian_config.content)
    brew_state.touch()

    for _ in range(2):
        result = subprocess.run(["bash", str(script)], check=False, capture_output=True, text=True, env=env)
        assert result.returncode == 0, result.stderr

    assert not legacy_helper.exists()
    assert not legacy_config.exists()
    assert not brew_state.exists()
    assert (tmp_path / "brew-uninstall.log").read_text() == "uninstalled\n"
    assert (home / ".local/bin/herd-local").stat().st_mode & 0o777 == 0o755
    assert (home / ".local/bin/herd-remote").stat().st_mode & 0o777 == 0o755
    assert (Path(env["XDG_CONFIG_HOME"]) / "herdr/local.toml").is_file()
    assert (Path(env["XDG_CONFIG_HOME"]) / "herdr/remote.toml").is_file()


def test_herdr_debian_upgrade_retires_legacy_helper(tmp_path: Path) -> None:
    script, _, env = _herdr_setup_harness(tmp_path, "debian")
    home = Path(env["HOME"])
    legacy_helper = home / ".local/bin/herd-agent"
    legacy_helper.parent.mkdir(parents=True)
    legacy_helper.write_text(_LEGACY_HERD_AGENT)

    result = subprocess.run(["bash", str(script)], check=False, capture_output=True, text=True, env=env)

    assert result.returncode == 0, result.stderr
    assert not legacy_helper.exists()
    assert (Path(env["XDG_CONFIG_HOME"]) / "herdr/config.toml").is_file()
    assert not (home / ".local/bin/herd-local").exists()
    assert not (home / ".local/bin/herd-remote").exists()


@pytest.mark.parametrize(
    ("legacy_name", "kind"),
    [("helper", "modified"), ("config", "symlink"), ("helper", "directory")],
)
def test_herdr_migration_preserves_legacy_conflicts(tmp_path: Path, legacy_name: str, kind: str) -> None:
    script, _, env = _herdr_setup_harness(tmp_path)
    legacy = Path(env["HOME"]) / ".local/bin/herd-agent" if legacy_name == "helper" else Path(env["XDG_CONFIG_HOME"]) / "herdr/config.toml"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    if kind == "modified":
        legacy.write_text("user managed\n")
    elif kind == "symlink":
        target = tmp_path / "user-config"
        target.write_text("user managed\n")
        legacy.symlink_to(target)
    else:
        legacy.mkdir()

    result = subprocess.run(["bash", str(script)], check=False, capture_output=True, text=True, env=env)

    assert result.returncode == 1
    assert "requires manual remediation" in result.stderr
    if kind == "modified":
        assert legacy.read_text() == "user managed\n"
    elif kind == "symlink":
        assert legacy.is_symlink() and legacy.read_text() == "user managed\n"
    else:
        assert legacy.is_dir()
    assert not (Path(env["HOME"]) / ".local/bin/herd-local").exists()


@pytest.mark.parametrize(
    ("launcher", "args", "expected_args", "config_name"),
    [
        ("herd-local", [], ["--session", "local"], "local.toml"),
        ("herd-local", ["custom-name"], ["--session", "custom-name"], "local.toml"),
        ("herd-remote", ["workbox"], ["--remote", "workbox"], "remote.toml"),
    ],
)
def test_herdr_launchers_execute_managed_binary(tmp_path: Path, launcher: str, args: list[str], expected_args: list[str], config_name: str) -> None:
    config = next(c for c in Herdr().render(ENVIRONMENTS["macos"]).configs if c.dest == f"herdr/{launcher}")
    home = tmp_path / "home"
    bin_dir = home / ".local/bin"
    bin_dir.mkdir(parents=True)
    herdr = bin_dir / "herdr"
    herdr.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$HERDR_ARGS"\nprintf "%s\\n" "$HERDR_CONFIG_PATH" > "$HERDR_CONFIG"\n')
    herdr.chmod(0o755)
    script = tmp_path / launcher
    script.write_text(config.content)
    script.chmod(config.mode)
    args_file = tmp_path / "args"
    config_file = tmp_path / "config"
    xdg_config = tmp_path / "xdg"
    env = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(xdg_config),
        "HERDR_ARGS": str(args_file),
        "HERDR_CONFIG": str(config_file),
        "PATH": "/usr/bin:/bin",
    }

    result = subprocess.run([script, *args], check=False, capture_output=True, text=True, env=env)

    assert result.returncode == 0, result.stderr
    assert args_file.read_text().splitlines() == expected_args
    assert config_file.read_text().strip() == str(xdg_config / "herdr" / config_name)


@pytest.mark.parametrize(
    ("launcher", "args", "usage"),
    [
        ("herd-local", [""], "usage: herd-local [session-name]"),
        ("herd-local", ["-bad"], "usage: herd-local [session-name]"),
        ("herd-local", ["one", "two"], "usage: herd-local [session-name]"),
        ("herd-remote", [], "usage: herd-remote <ssh-config-host>"),
        ("herd-remote", [""], "usage: herd-remote <ssh-config-host>"),
        ("herd-remote", ["-bad"], "usage: herd-remote <ssh-config-host>"),
        ("herd-remote", ["one", "two"], "usage: herd-remote <ssh-config-host>"),
    ],
)
def test_herdr_launchers_reject_invalid_arguments(tmp_path: Path, launcher: str, args: list[str], usage: str) -> None:
    config = next(c for c in Herdr().render(ENVIRONMENTS["macos"]).configs if c.dest == f"herdr/{launcher}")
    script = tmp_path / launcher
    script.write_text(config.content)
    script.chmod(config.mode)

    result = subprocess.run([script, *args], check=False, capture_output=True, text=True, env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})

    assert result.returncode == 2
    assert usage in result.stderr


@pytest.mark.parametrize("launcher", ["herd-local", "herd-remote"])
@pytest.mark.parametrize("binary_kind", ["missing", "directory", "non-executable"])
def test_herdr_launchers_reject_invalid_managed_binary(tmp_path: Path, launcher: str, binary_kind: str) -> None:
    config = next(c for c in Herdr().render(ENVIRONMENTS["macos"]).configs if c.dest == f"herdr/{launcher}")
    home = tmp_path / "home"
    binary = home / ".local/bin/herdr"
    binary.parent.mkdir(parents=True)
    if binary_kind == "directory":
        binary.mkdir()
    elif binary_kind == "non-executable":
        binary.write_text("not executable\n")
    script = tmp_path / launcher
    script.write_text(config.content)
    script.chmod(config.mode)
    args = ["workbox"] if launcher == "herd-remote" else []

    result = subprocess.run([script, *args], check=False, capture_output=True, text=True, env={"HOME": str(home), "PATH": "/usr/bin:/bin"})

    assert result.returncode == 1
    assert f"{launcher}: managed Herdr binary is missing or invalid" in result.stderr


def test_starship_emits_config_and_init() -> None:
    frag = Starship().render(ENVIRONMENTS["macos"])
    assert any(c.dest == "starship/starship.toml" for c in frag.configs)
    assert "starship init bash" in frag.bashrc
    assert 'install_config "$DIR/config/starship/starship.toml" "${XDG_CONFIG_HOME:-$HOME/.config}/starship.toml"' in frag.setup
    cfg = next(c for c in frag.configs if c.dest == "starship/starship.toml").content
    assert 'format = "$directory$git_branch$git_status$kubernetes$line_break$character"' in cfg
    assert "add_newline = true" in cfg
    assert "[kubernetes]" in cfg
    assert "context_pattern" in cfg
    for disabled in ("[gcloud]", "[aws]", "[docker_context]", "[dotnet]"):
        assert disabled in cfg


def test_kubectl_per_os_branching() -> None:
    macos = Kubectl().render(ENVIRONMENTS["macos"]).setup
    debian = Kubectl().render(ENVIRONMENTS["debian"]).setup
    assert "install_packages kubectl helm k9s kubectx" in macos
    assert "_install_helm_linux" not in macos
    assert "add_repo" not in debian
    assert "_install_kubectl_linux" in debian
    assert "_install_helm_linux" in debian
    assert "_install_k9s_linux" in debian
    assert "_install_kubectx_linux" in debian
    assert "_install_kubens_linux" in debian
    assert 'download_bin kubectl "https://dl.k8s.io/release/v1.35.8/bin/linux/${arch}/kubectl" "v1.35.8" version --client' in debian
    assert 'download_tar_bin helm "https://get.helm.sh/helm-v3.21.4-linux-${arch}.tar.gz" "linux-${arch}/helm" "v3.21.4" version --template \'{{.Version}}\'' in debian
    assert 'download_tar_bin k9s "https://github.com/derailed/k9s/releases/download/v0.51.0/k9s_Linux_${arch}.tar.gz" "k9s" "v0.51.0" version --short' in debian
    assert "releases/latest" not in debian
    assert 'download_tar_bin kubectx "https://github.com/ahmetb/kubectx/releases/download/v0.11.0/kubectx_v0.11.0_linux_${arch}.tar.gz" "kubectx" "v0.11.0" --version' in debian
    assert 'download_tar_bin kubens "https://github.com/ahmetb/kubectx/releases/download/v0.11.0/kubens_v0.11.0_linux_${arch}.tar.gz" "kubens" "v0.11.0" --version' in debian
    assert 'download_bin kubie "https://github.com/sbstp/kubie/releases/download/v0.28.0/kubie-linux-${arch}" "0.28.0" --version' in debian
    assert "kubie generate-completion" in Kubectl().render(ENVIRONMENTS["debian"]).bashrc
    aliases = Kubectl().render(ENVIRONMENTS["macos"]).alias
    assert "alias kca=" not in aliases
    assert "alias kcn='kubectl ns'" in aliases
    assert "alias kcr=" not in aliases
    assert 'kubectl -n "${ns}" get secret "${secret}" -o json' in aliases
    assert "@base64d" in aliases


def test_gcloud_retains_selected_public_helpers() -> None:
    aliases = Gcloud().render(ENVIRONMENTS["macos"]).alias
    assert "alias gcp='gcloud config configurations activate default'" in aliases
    assert "get_project_roles()" in aliases
    assert "get_sa_bindings()" in aliases


def test_claude_code_settings() -> None:
    frag = ClaudeCode().render(ENVIRONMENTS["macos"])
    assert {config.dest for config in frag.configs} == {"managed-settings/claude.json"}
    cfg = frag.configs[0]
    assert cfg.mode == 0o600
    assert '"includeCoAuthoredBy": false' in cfg.content
    assert '"defaultMode": "auto"' in cfg.content
    assert '"skipAutoPermissionPrompt": true' in cfg.content
    assert '"skipWorkflowUsageWarning": true' in cfg.content
    assert '"theme": "light"' in cfg.content
    assert '"tui": "fullscreen"' in cfg.content
    assert '"SessionStart"' in cfg.content
    assert "~/.claude/hooks/serena-reminder.sh" in cfg.content


def test_claude_code_setup_installs_serena_via_uv_tool() -> None:
    setup = ClaudeCode().render(ENVIRONMENTS["macos"]).setup
    assert setup.count('install_config_dir "$DIR/config/claude" "$HOME/.claude" "claude" "settings.json"') == 1
    assert setup.count('install_json_patch "$DIR/config/managed-settings/claude.json" "$HOME/.claude/settings.json" 0600') == 1
    assert setup.count('install_config "$DIR/config/repositories/platform/CLAUDE.md" "$HOME/repos/platform/CLAUDE.md"') == 1
    assert 'install_config "$DIR/config/claude/settings.json" "$HOME/.claude/settings.json"' not in setup
    assert 'install_config "$DIR/config/claude/CLAUDE.md"' not in setup
    assert 'install_config "$DIR/config/claude/hooks/serena-reminder.sh"' not in setup
    assert "chmod" not in setup
    assert "tool install --from https://github.com/oraios/serena/archive/refs/heads/main.tar.gz serena-agent" in setup
    assert "claude mcp list" not in setup
    assert "jq -e '.mcpServers.serena // empty'" in setup
    assert "claude mcp add serena -s user -- serena start-mcp-server --context claude-code" in setup


def test_claude_code_runs_after_python_tools() -> None:
    for env in ENVIRONMENTS.values():
        names = [c.name for c in env.components]
        if "python_tools" in names and "claude_code" in names:
            assert names.index("python_tools") < names.index("claude_code"), f"{env.name}: claude_code must follow python_tools so uv is available"


def test_python_tools_per_os_build_deps() -> None:
    debian = PythonTools().render(ENVIRONMENTS["debian"]).setup
    macos = PythonTools().render(ENVIRONMENTS["macos"]).setup
    assert "build-essential" in debian
    assert "install_packages" not in macos.split("install_script uv")[0]
    for setup in (debian, macos):
        assert "install_script uv https://astral.sh/uv/install.sh" in setup
        assert 'export PATH="$HOME/.local/bin:$PATH"' in setup
        assert "uv tool install python-lsp-server" in setup


def test_go_lang_has_no_macos_package_dependency() -> None:
    assert GoLang().applies_to(ENVIRONMENTS["debian"])
    assert GoLang().applies_to(ENVIRONMENTS["macos"])
    macos = GoLang().render(ENVIRONMENTS["macos"]).setup
    assert 'GO_VERSION="1.25.5"' in macos
    assert "mercurial" not in macos
    assert "install_packages" not in macos


def test_aws_emits_config_with_secure_mode() -> None:
    frag = Aws().render(ENVIRONMENTS["macos"])
    cfg = next(c for c in frag.configs if c.dest == "aws/config")
    assert cfg.mode == 0o600
    assert "[default]" in cfg.content


def test_environment_component_distribution() -> None:
    debian_names = {c.name for c in ENVIRONMENTS["debian"].components}
    macos_names = {c.name for c in ENVIRONMENTS["macos"].components}
    shared_names = {
        "bash_base",
        "core_utils",
        "fzf_bash_history",
        "tmux",
        "mosh",
        "herdr",
        "helix",
        "starship",
        "zoxide",
        "kubectl",
        "python_tools",
        "claude_code",
        "gh",
        "git_signing",
        "rust",
        "terraform",
        "node_fnm",
        "npm_config",
        "go_lang",
        "gcloud",
        "aws",
        "doppler",
        "fonts",
    }
    assert shared_names.issubset(debian_names & macos_names)
    assert {"ghostty", "zed", "orbstack"}.isdisjoint(debian_names)
    assert {"ghostty", "zed", "orbstack"}.issubset(macos_names)
    assert "supacode" not in debian_names | macos_names
    assert "node_fnm" in {c.name for c in ENVIRONMENTS["debian-docker"].components}


def test_doppler_is_full_only_and_renders_per_os() -> None:
    doppler = Doppler()
    assert doppler.applies_to(ENVIRONMENTS["debian"])
    assert doppler.applies_to(ENVIRONMENTS["macos"])
    assert not doppler.applies_to(ENVIRONMENTS["debian-docker"])

    for env_name in ("debian", "macos"):
        names = [component.name for component in ENVIRONMENTS[env_name].components]
        assert names.count("doppler") == 1
    assert "doppler" not in [component.name for component in ENVIRONMENTS["debian-docker"].components]

    debian = doppler.render(ENVIRONMENTS["debian"]).setup
    assert "install_packages apt-transport-https ca-certificates curl gnupg" in debian
    assert "add_repo apt doppler-cli" in debian
    assert "https://packages.doppler.com/public/cli/deb/debian any-version main" in debian
    assert "https://packages.doppler.com/public/cli/gpg.DE2A7741A397C129.key" in debian
    assert debian.index("update_pkg_index") < debian.index("install_package doppler")

    macos = doppler.render(ENVIRONMENTS["macos"]).setup
    assert "install_package gnupg" in macos
    assert "if ! bin_exists doppler" in macos
    assert "install_package dopplerhq/cli/doppler" in macos


def test_docker_is_full_debian_only_and_ordered_before_final_deployers() -> None:
    assert Docker().applies_to(ENVIRONMENTS["debian"])
    assert not Docker().applies_to(ENVIRONMENTS["debian-docker"])
    assert not Docker().applies_to(ENVIRONMENTS["macos"])
    for name in ("debian-docker", "macos"):
        assert "docker" not in [component.name for component in ENVIRONMENTS[name].components]
    names = [component.name for component in ENVIRONMENTS["debian"].components]
    assert names.count("docker") == 1
    assert names[-5:] == ["tmuxinator", "docker", "zed_host_bridge", "git_setup", "dotfiles_deploy"]


def test_docker_render_contract() -> None:
    frag = Docker().render(ENVIRONMENTS["debian"])
    assert frag.setup and not frag.alias and not frag.bashrc and not frag.configs and not frag.vendors and not frag.secrets
    setup = frag.setup
    for token in (
        "https://download.docker.com/linux/debian/gpg",
        "Types: deb",
        "URIs: https://download.docker.com/linux/debian",
        "Suites: trixie",
        "Components: stable",
        "Signed-By: /etc/apt/keyrings/docker.asc",
        "install_package uidmap",
        "add_repo apt-deb822 docker",
        "remove_packages docker.io docker-compose docker-doc podman-docker containerd runc",
        "service_mask docker.service docker.socket",
        'sudo modprobe "$module"',
        "update_pkg_index",
        "install_packages docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras",
        "install_package kmod",
    ):
        assert token in setup
    for forbidden in (
        "apt-get",
        "brew install",
        "service_enable docker",
        "--force",
        "usermod",
        "groupadd",
        "docker group",
        "rm -rf /var/lib/docker",
        "rm -rf /var/lib/containerd",
        "export DOCKER_HOST",
    ):
        assert forbidden not in setup
    sandbox = next(c for c in PiAgent().render(ENVIRONMENTS["debian"]).configs if c.dest == "pi/sandbox/pi-sandbox.sh").content
    assert "docker.sock" not in sandbox


def test_npm_config_is_ordered_between_node_and_pi_in_every_environment() -> None:
    for env in ENVIRONMENTS.values():
        names = [component.name for component in env.components]
        if "pi_agent" in names:
            assert names.index("node_fnm") < names.index("npm_config") < names.index("pi_agent")


def test_ghostty_macos_only_and_emits_config() -> None:
    assert Ghostty().applies_to(ENVIRONMENTS["macos"])
    assert not Ghostty().applies_to(ENVIRONMENTS["debian"])
    frag = Ghostty().render(ENVIRONMENTS["macos"])
    cfg = next(c for c in frag.configs if c.dest == "ghostty/config").content
    assert "theme = Tomorrow" in cfg
    assert "background-opacity = 1" in cfg
    assert "background-blur = false" in cfg
    assert "unfocused-split-opacity = 1" in cfg
    assert "shell-integration-features = ssh-env,ssh-terminfo" in cfg
    assert "scrollback-limit = 100_000_000" in cfg
    assert "keybind = shift+enter=text:\\x0a" in cfg
    assert "install_cask ghostty" in frag.setup
    assert "Library/Application Support/com.mitchellh.ghostty" in frag.setup


def test_gh_emits_config_in_every_env() -> None:
    for env_name in ("debian", "macos"):
        frag = Gh().render(ENVIRONMENTS[env_name])
        assert any(c.dest == "gh/config.yml" for c in frag.configs)
        assert "co: pr checkout" in next(c for c in frag.configs if c.dest == "gh/config.yml").content


def test_gh_per_os_install() -> None:
    debian = Gh().render(ENVIRONMENTS["debian"]).setup
    macos = Gh().render(ENVIRONMENTS["macos"]).setup
    assert "add_repo apt githubcli" in debian and "install_package gh" in debian
    assert "install_package gh" in macos and "add_repo" not in macos
    for setup in (debian, macos):
        assert "gh extension install github/gh-stack" in setup


def test_zed_macos_only_and_emits_configs() -> None:
    debian_names = {c.name for c in ENVIRONMENTS["debian"].components}
    assert "zed" not in debian_names
    frag = Zed().render(ENVIRONMENTS["macos"])
    dests = sorted(c.dest for c in frag.configs)
    assert dests == ["zed/keymap.json", "zed/settings.json"]
    settings = next(c for c in frag.configs if c.dest == "zed/settings.json").content
    assert '"cli_default_open_behavior": "new_window"' in settings
    assert '"diff_view_style": "unified"' in settings
    assert '"buffer_font_family": ".ZedMono"' in settings
    assert '"**/deploy/helm/templates/**/*.yaml"' in settings
    macos = Zed().render(ENVIRONMENTS["macos"]).setup
    assert "install_cask zed" in macos


def test_orbstack_macos_only_and_installs_cask() -> None:
    assert OrbStack().applies_to(ENVIRONMENTS["macos"])
    assert not OrbStack().applies_to(ENVIRONMENTS["debian"])
    assert OrbStack().render(ENVIRONMENTS["macos"]).setup == "install_cask orbstack\n"


def test_install_script_used_for_curl_installers() -> None:
    expected = {
        "starship": "install_script starship https://starship.rs/install.sh -y",
        "rust": "install_script rustup https://sh.rustup.rs -y --default-toolchain stable",
        "node_fnm": 'install_script fnm https://fnm.vercel.app/install --skip-shell --force-install --install-dir "$HOME/.local/share/fnm"',
        "claude_code": "install_script claude https://claude.ai/install.sh",
    }
    renders = {
        "starship": Starship().render(ENVIRONMENTS["macos"]).setup,
        "rust": Rust().render(ENVIRONMENTS["macos"]).setup,
        "node_fnm": NodeFnm().render(ENVIRONMENTS["macos"]).setup,
        "claude_code": ClaudeCode().render(ENVIRONMENTS["macos"]).setup,
    }
    for name, expected_line in expected.items():
        body = renders[name]
        assert expected_line in body, f"{name} missing install_script call"
        assert "curl " not in body, f"{name} still has raw curl invocation"


def test_node_fnm_activates_latest_lts_during_setup() -> None:
    frag = NodeFnm().render(ENVIRONMENTS["debian"])
    assert 'fnm_bin="$(command -v fnm 2>/dev/null || true)"' in frag.setup
    assert 'fnm_bin="$HOME/.local/share/fnm/fnm"' in frag.setup
    assert "exit 1" in frag.setup
    assert 'eval "$("$fnm_bin" env --shell bash)"' in frag.setup
    assert '"$fnm_bin" install --lts --use' in frag.setup
    assert 'eval "$(fnm env --use-on-cd --shell bash)"' in frag.bashrc


def test_dotfiles_deploy_emits_bashrc_alias_install_and_private_overlay() -> None:
    for env in ENVIRONMENTS.values():
        fragment = DotfilesDeploy().render(env)
        assert 'install_config "$DIR/.bashrc" "$HOME/.bashrc"' in fragment.setup
        assert 'install_config "$DIR/alias.sh" "$HOME/.aliases"' in fragment.setup
        assert 'private_dotfiles_installer="$HOME/repos/dotfiles-private/install.sh"' in fragment.setup
        assert '[ -r "$private_dotfiles_installer" ]' in fragment.setup
        assert 'PATH="$HOME/.local/bin:$(printenv PATH)" bash "$private_dotfiles_installer"' in fragment.setup
        assert fragment.alias == '[ -r "${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/private-aliases.sh" ] && source "${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/private-aliases.sh"\n'


def test_dotfiles_deploy_sets_macos_login_locale() -> None:
    macos_profile = DotfilesDeploy().render(ENVIRONMENTS["macos"]).configs[0].content
    debian_profile = DotfilesDeploy().render(ENVIRONMENTS["debian"]).configs[0].content

    assert macos_profile.startswith('export LANG="${LANG:-en_US.UTF-8}"\n')
    assert "export LANG=" not in debian_profile


@pytest.mark.parametrize("env_name", ENVIRONMENTS)
def test_dotfiles_deploy_refreshes_private_overlay_with_local_starship(tmp_path: Path, env_name: str) -> None:
    home = tmp_path / "home"
    bundle = tmp_path / "bundle"
    for relative in (".bashrc", "alias.sh", "config/bash/bash_profile"):
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative}\n")

    public_starship = home / ".config/starship.toml"
    public_starship.parent.mkdir(parents=True)
    public_starship.write_text("add_newline = true\n")

    starship = home / ".local/bin/starship"
    starship.parent.mkdir(parents=True)
    starship.write_text("#!/usr/bin/env bash\nexit 0\n")
    starship.chmod(0o755)

    private_installer = home / "repos/dotfiles-private/install.sh"
    private_installer.parent.mkdir(parents=True)
    private_installer.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\ncommand -v starship >/dev/null\ngrep -Fq \'add_newline = true\' "${XDG_CONFIG_HOME:-$HOME/.config}/starship.toml"\n: > "$HOME/private-installer-ran"\n'
    )

    setup = DotfilesDeploy().render(ENVIRONMENTS[env_name]).setup
    script = f'set -euo pipefail\nDIR=$1\ninstall_config() {{ mkdir -p "$(dirname "$2")"; cp "$1" "$2"; }}\n{setup}'
    result = subprocess.run(
        ["/bin/bash", "-c", script, "_", str(bundle)],
        check=False,
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert (home / "private-installer-ran").is_file()


def test_dotfiles_deploy_runs_last_in_every_env() -> None:
    for env in ENVIRONMENTS.values():
        assert env.components[-1].name == "dotfiles_deploy", f"{env.name}: dotfiles_deploy must run last"


def test_postgres_renders_per_os() -> None:
    for env_name in ("debian", "macos"):
        env = ENVIRONMENTS[env_name]
        frag = Postgres().render(env)
        assert frag.bashrc and "PATH" in frag.bashrc
    mac = Postgres().render(ENVIRONMENTS["macos"]).setup
    deb = Postgres().render(ENVIRONMENTS["debian"]).setup
    assert "install_package postgresql@18" in mac
    assert "add_repo apt pgdg" in deb and "postgresql-18" in deb


def test_pi_agent_setup() -> None:
    frag = PiAgent().render(ENVIRONMENTS["macos"])
    npm_lines = [line for line in frag.setup.splitlines() if line.startswith("install_npm_global ")]
    assert len(npm_lines) == 1
    assert shlex.split(npm_lines[0]) == ["install_npm_global", *_PI_PACKAGES]
    assert "npm uninstall -g pi-lens" in frag.setup
    assert "pi-web-access" not in npm_lines[0]
    assert 'install_config_dir "$DIR/config/pi/agent" "$HOME/.pi/agent" "pi-agent" "settings.json"' in frag.setup
    assert 'install_json_patch "$DIR/config/managed-settings/pi.json" "$HOME/.pi/agent/settings.json" 0600' in frag.setup
    assert 'install -m 0755 "$DIR/config/pi/launcher/pi.sh" "$HOME/.local/bin/pi"' in frag.setup
    assert 'install -m 0755 "$DIR/config/pi/sandbox/pi-sandbox.sh" "$HOME/.local/bin/pi-sandbox"' in frag.setup
    assert "GEMINI_API_KEY" not in frag.secrets
    assert "GCP_PROJECT_ID" in frag.secrets
    assert "EXA_API_KEY" in frag.secrets
    assert "CONTEXT7_API_KEY" in frag.secrets
    settings = next(cf for cf in frag.configs if cf.dest == "managed-settings/pi.json")
    assert settings.mode == 0o600
    assert '"defaultModel": "gpt-5.6-sol"' in settings.content
    assert '"defaultThinkingLevel": "high"' in settings.content
    assert "openai-codex/gpt-5.6-luna" in settings.content
    assert "openai-codex/gpt-5.6-terra" in settings.content
    assert "lastChangelogVersion" not in settings.content
    assert "npm:@plannotator/pi-extension" in settings.content
    assert "npm:@dreki-gg/pi-context7" in settings.content
    assert "npm:@spences10/pi-lsp" in settings.content
    assert "pi-lens" not in settings.content
    assert "npm:@juicesharp/rpiv-btw" in settings.content
    assert "npm:@vanillagreen/pi-web-tools" in settings.content
    assert "npm:pi-web-access" not in settings.content
    assert '"~/repos/pi-angelini"' in settings.content
    assert "install_npm_global ~/repos/pi-angelini" not in frag.setup
    assert 'install_config_dir "$DIR/config/pi-angelini" "$HOME/repos/pi-angelini"' in frag.setup
    dests = {cf.dest for cf in frag.configs}
    assert dests == {
        "managed-settings/pi.json",
        "pi/agent/models.json",
        "pi/agent/web-search.json",
        "pi/agent/plannotator.json",
        "pi/launcher/pi.sh",
        "pi/sandbox/pi-sandbox.sh",
        "pi/sandbox/pi-macos.sb",
    }
    assert not [d for d in dests if d.startswith("pi-angelini/")]
    plannotator = next(cf for cf in frag.configs if cf.dest == "pi/agent/plannotator.json")
    phases = json.loads(plannotator.content)["phases"]
    assert all("instructions" in phase for phase in phases.values())
    assert all("systemPrompt" not in phase for phase in phases.values())
    agent_vendor, angelini_vendor = frag.vendors
    assert agent_vendor.source == _agent_config_root() / "pi" / "agent"
    assert agent_vendor.dest == "pi/agent"
    assert agent_vendor.include_globs == (
        "AGENTS.md",
        "APPEND_SYSTEM.md",
        "agents/claude-pipeline/*.md",
        "chains/pipeline.chain.md",
        "prompts/pipeline.md",
        "skills/pipeline/**",
    )
    assert angelini_vendor.source == _pi_angelini_root()
    assert angelini_vendor.dest == "pi-angelini"
    assert angelini_vendor.exclude_dirs == GIT_ARTIFACTS | NODE_ARTIFACTS | PY_ARTIFACTS | frozenset({".pi-lens", ".pi-subagents", ".serena", "dist"})
    assert angelini_vendor.exclude_globs == ("package-lock.json", "pi-system-audit-plan.md", "*.test.ts")


def test_history_paths_remain_hidden_from_pi() -> None:
    assert ".local/share/stinkpot" in SANDBOX_HOME_POLICY.hidden_dirs
    assert ".bash_history" in SANDBOX_HOME_POLICY.hidden_files


def test_pi_agent_sandbox_aliases() -> None:
    frag = PiAgent().render(ENVIRONMENTS["macos"])
    assert 'pi-sandbox "$@"' in frag.alias
    assert 'command pi "$@"' in frag.alias


def test_pi_agent_launcher_uses_fnm_default() -> None:
    frag = PiAgent().render(ENVIRONMENTS["debian"])
    launcher = next(cf for cf in frag.configs if cf.dest == "pi/launcher/pi.sh")
    assert launcher.mode == 0o755
    assert 'node_bin="${FNM_DIR:-$HOME/.local/share/fnm}/aliases/default/bin"' in launcher.content
    assert 'export PATH="$node_bin:$PATH"' in launcher.content
    assert 'exec "$pi_bin" "$@"' in launcher.content


def test_pi_agent_bubblewrap_linux_only() -> None:
    assert "install_package bubblewrap" in PiAgent().render(ENVIRONMENTS["debian"]).setup
    assert "install_package bubblewrap" not in PiAgent().render(ENVIRONMENTS["macos"]).setup


def test_pi_agent_sandbox_configs() -> None:
    frag = PiAgent().render(ENVIRONMENTS["macos"])
    script = next(cf for cf in frag.configs if cf.dest == "pi/sandbox/pi-sandbox.sh")
    profile = next(cf for cf in frag.configs if cf.dest == "pi/sandbox/pi-macos.sb")
    models = next(cf for cf in frag.configs if cf.dest == "pi/agent/models.json")
    assert script.mode == 0o755
    assert script.content.count('"DOTGEN_PI_SANDBOX=1"') == 2
    assert {
        ".ssh",
        ".gnupg",
        ".aws",
        ".azure",
        ".config/dotgen",
        ".kube",
    } <= set(SANDBOX_HOME_POLICY.hidden_dirs)
    assert ".config/gcloud" not in SANDBOX_HOME_POLICY.hidden_dirs
    assert ".config/gcloud/application_default_credentials.json" in SANDBOX_HOME_POLICY.readonly_files
    assert ".local/share/stinkpot" in SANDBOX_HOME_POLICY.hidden_dirs
    assert ".local/share/stinkpot" not in SANDBOX_HOME_POLICY.hidden_files
    assert ".bash_history" in SANDBOX_HOME_POLICY.hidden_files
    assert ".local/share" in SANDBOX_HOME_POLICY.writable_dirs
    assert ".pi-lens" in SANDBOX_HOME_POLICY.writable_dirs
    assert {
        ".docker/config.json",
        ".config/gh/hosts.yml",
        ".config/git/credentials",
        ".config/helm/registry/config.json",
        ".config/helm/repositories.yaml",
        ".git-credentials",
        ".netrc",
        ".npmrc",
        ".pypirc",
        ".cargo/credentials",
        ".cargo/credentials.toml",
    } <= set(SANDBOX_HOME_POLICY.hidden_files)

    for path in SANDBOX_HOME_POLICY.writable_dirs:
        assert f'--bind "$HOME/{path}" "$HOME/{path}"' in script.content
        sbpl = f'(subpath (string-append (param "HOME") "/{path}"))'
        assert profile.content.count(sbpl) == 2
    for path in SANDBOX_HOME_POLICY.readonly_dirs:
        assert f'--ro-bind "$HOME/{path}" "$HOME/{path}"' in script.content
        sbpl = f'(subpath (string-append (param "HOME") "/{path}"))'
        assert profile.content.count(sbpl) == 2
    for path in SANDBOX_HOME_POLICY.readonly_files:
        assert f'--ro-bind-try "$HOME/{path}" "$HOME/{path}"' in script.content
        sbpl = f'(literal (string-append (param "HOME") "/{path}"))'
        assert profile.content.count(sbpl) == 2
    for path in SANDBOX_HOME_POLICY.hidden_dirs:
        assert f'--tmpfs "$HOME/{path}"' in script.content
        sbpl = f'(subpath (string-append (param "HOME") "/{path}"))'
        assert profile.content.count(sbpl) == 1
    for path in SANDBOX_HOME_POLICY.hidden_files:
        assert f'--ro-bind /dev/null "$HOME/{path}"' in script.content
        sbpl = f'(literal (string-append (param "HOME") "/{path}"))'
        assert profile.content.count(sbpl) == 1

    assert 'jiti_cache="$HOME/.pi-sandbox-cache/jiti"' in script.content
    assert script.content.count('"JITI_FS_CACHE=1"') == 2
    assert "refusing symlinked Jiti cache directory" in script.content
    assert 'herdr_clipboard_images="/tmp/herdr-clipboard-images-$(id -u)"' in script.content
    assert "refusing symlinked Herdr clipboard image directory" in script.content
    assert 'owner="$(stat -c %u "$path")"' in script.content
    assert '--ro-bind "$herdr_clipboard_images" "$herdr_clipboard_images"' in script.content
    assert 'chmod 0700 "$cache_parent"' in script.content
    assert 'chmod 0700 "$cache"' in script.content
    clipboard_bind = '--ro-bind "$herdr_clipboard_images" "$herdr_clipboard_images"'
    jiti_bind = '--bind "$jiti_cache" /tmp/jiti'
    assert script.content.index("--tmpfs /tmp") < script.content.index(clipboard_bind) < script.content.index(jiti_bind)
    assert script.content.index('herdr_clipboard_images="$(_prepare_herdr_clipboard_images "$herdr_clipboard_images")"') < script.content.rindex("exec env -i")
    assert script.content.index('jiti_cache="$(_prepare_jiti_cache "$jiti_cache")"') < script.content.rindex("exec env -i")
    assert 'transformers_cache="$memory_dir/transformers-cache"' in script.content
    assert 'transformers_cache_target="$(npm root -g)/@samfp/pi-memory/' in script.content
    fnm_bind = '--ro-bind "$HOME/.local/share/fnm" "$HOME/.local/share/fnm"'
    cache_bind = '--bind "$transformers_cache" "$transformers_cache_target"'
    assert script.content.index(fnm_bind) < script.content.index(cache_bind)
    assert '-D "TRANSFORMERS_CACHE=$transformers_cache_target"' in script.content
    assert '-D "HOME_PARENT=$(dirname "$HOME")"' in script.content
    assert 'tmpdir="$(_resolve_path "${TMPDIR:-/tmp}")"' in script.content
    assert '"TMPDIR=$tmpdir"' in script.content
    assert '-D "TMPDIR=$tmpdir"' in script.content
    assert '(literal (param "HOME_PARENT"))' in profile.content
    assert '(subpath (param "HOME"))' in profile.content
    assert '(subpath (param "TMPDIR"))' in profile.content
    assert '(allow file-read-data file-test-existence file-write-data\n  (subpath "/dev/fd"))' in profile.content
    assert '(subpath (param "TRANSFORMERS_CACHE"))' in profile.content
    assert 'runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"' in script.content
    assert '--ro-bind-try "$runtime_dir/fnm_multishells" "$runtime_dir/fnm_multishells"' in script.content
    assert '--setenv XDG_RUNTIME_DIR "$runtime_dir"' in script.content
    assert "--unshare-net" not in script.content
    assert "(allow network*)" in profile.content
    assert '(literal "/private/var/run/mDNSResponder")' in profile.content
    assert '(literal "/etc")' in profile.content
    assert '(literal "/var")' in profile.content
    assert 'bin="${FNM_DIR:-$HOME/.local/share/fnm}/aliases/default/bin"' in script.content
    assert 'node_bin="$(_fnm_default_bin)"' in script.content
    assert script.content.index('PATH="$node_bin:$PATH"') < script.content.index('pi_bin="$(command -v pi)"')
    assert 'pi_bin="$(command -v pi)"' in script.content
    assert '"$pi_bin" "$@"' in script.content
    assert "GEMINI_API_KEY" not in script.content
    assert "GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT:-${GCP_PROJECT_ID:-}}" in script.content
    assert "GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION:-europe-west4}" in script.content
    assert "EXA_API_KEY=${EXA_API_KEY:-}" in script.content
    assert "CONTEXT7_API_KEY=${CONTEXT7_API_KEY:-}" in script.content
    assert "__SANDBOX_" not in script.content
    assert "__MACOS_" not in profile.content
    parsed_models = json.loads(models.content)
    vertex = parsed_models["providers"]["google-vertex"]
    assert vertex["api"] == "google-vertex"
    assert "apiKey" not in vertex
    assert vertex["models"][0]["id"] == "gemini-3-flash-preview"


_VENDOR_SRC = Path(__file__).parent / "fixtures" / "vendor_src"
_AGENT_CONFIG_SRC = _VENDOR_SRC / "build" / "agent-config"


def _vendored(v: VendorDir, out: Path) -> dict[str, bytes]:
    _vendor_dir(v, out)
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


def test_agent_config_root_override_and_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOTGEN_AGENT_CONFIG_ROOT", "/fixture/agent-config")
    assert _agent_config_root() == Path("/fixture/agent-config")
    monkeypatch.delenv("DOTGEN_AGENT_CONFIG_ROOT")
    assert _agent_config_root() == Path(agent_config_module.__file__).resolve().parents[4] / "agent-config"


def test_managed_settings_uses_override_and_canonicalizes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "agent-config"
    settings = root / "settings"
    settings.mkdir(parents=True)
    (settings / "claude.managed.json").write_text('{"z":1,"nested":{"b":2,"a":1}}')
    monkeypatch.setenv("DOTGEN_AGENT_CONFIG_ROOT", str(root))

    assert managed_settings("claude") == '{\n  "nested": {\n    "a": 1,\n    "b": 2\n  },\n  "z": 1\n}\n'


def test_pi_models_uses_agent_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "agent-config"
    models = root / "pi" / "agent" / "models.json"
    models.parent.mkdir(parents=True)
    models.write_text('{"providers":{"google-vertex":{"api":"google-vertex"}}}')
    monkeypatch.setenv("DOTGEN_AGENT_CONFIG_ROOT", str(root))

    assert json.loads(pi_models()) == {"providers": {"google-vertex": {"api": "google-vertex"}}}


@pytest.mark.parametrize("content", ["{bad", "[]", "null", '"value"', "{}\n{}\n", '{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}'])
def test_managed_settings_rejects_invalid_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str) -> None:
    root = tmp_path / "agent-config"
    path = root / "settings" / "claude.managed.json"
    path.parent.mkdir(parents=True)
    path.write_text(content)
    monkeypatch.setenv("DOTGEN_AGENT_CONFIG_ROOT", str(root))

    with pytest.raises(ValueError, match="managed settings") as exc_info:
        managed_settings("claude")
    assert str(path) in str(exc_info.value)


def test_managed_settings_missing_patch_names_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "agent-config"
    monkeypatch.setenv("DOTGEN_AGENT_CONFIG_ROOT", str(root))

    with pytest.raises(FileNotFoundError) as exc_info:
        managed_settings("claude")
    assert exc_info.value.filename == str(root / "settings" / "claude.managed.json")


def test_agent_config_components_share_disjoint_filtered_namespaces(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOTGEN_AGENT_CONFIG_ROOT", str(_AGENT_CONFIG_SRC))
    claude = ClaudeCode().render(ENVIRONMENTS["macos"])
    pi = PiAgent().render(ENVIRONMENTS["macos"])
    claude_vendor = next(vendor for vendor in claude.vendors if vendor.dest == "claude")
    platform_vendor = next(vendor for vendor in claude.vendors if vendor.dest == "repositories/platform")
    pi_vendor = next(vendor for vendor in pi.vendors if vendor.dest == "pi/agent")

    assert claude_vendor.source == _AGENT_CONFIG_SRC / "claude"
    assert claude_vendor.dest == "claude"
    assert claude_vendor.include_globs == ("CLAUDE.md", "agents/*.md", "commands/review.md", "hooks/*", "skills/**")
    assert platform_vendor.source == _AGENT_CONFIG_SRC / "repositories" / "platform"
    assert platform_vendor.include_globs == ("CLAUDE.md",)
    assert pi_vendor.source == _AGENT_CONFIG_SRC / "pi" / "agent"
    assert pi_vendor.dest == "pi/agent"
    assert pi_vendor.include_globs == (
        "AGENTS.md",
        "APPEND_SYSTEM.md",
        "agents/claude-pipeline/*.md",
        "chains/pipeline.chain.md",
        "prompts/pipeline.md",
        "skills/pipeline/**",
    )
    assert set(_vendored(claude_vendor, tmp_path / "claude")) == {
        "CLAUDE.md",
        "agents/reviewer.md",
        "commands/review.md",
        "hooks/fixture-hook.sh",
        "skills/fixture/SKILL.md",
    }
    assert set(_vendored(platform_vendor, tmp_path / "platform")) == {"CLAUDE.md"}
    assert set(_vendored(pi_vendor, tmp_path / "pi")) == {
        "AGENTS.md",
        "APPEND_SYSTEM.md",
        "agents/claude-pipeline/reviewer.md",
        "chains/pipeline.chain.md",
        "prompts/pipeline.md",
        "skills/pipeline/SKILL.md",
    }
    assert "README.md" not in _vendored(claude_vendor, tmp_path / "claude-again")
    assert "extensions/context7/cache/generated.json" not in _vendored(pi_vendor, tmp_path / "pi-again")
    assert len(claude.vendors) == 2
    assert {config.dest for config in claude.configs} == {"managed-settings/claude.json"}
    claude_settings = claude.configs[0]
    assert claude_settings.mode == 0o600
    managed_claude = json.loads(claude_settings.content)
    assert managed_claude["permissions"]["defaultMode"] == "auto"
    assert managed_claude["skipAutoPermissionPrompt"] is True
    assert managed_claude["skipWorkflowUsageWarning"] is True
    assert managed_claude["theme"] == "light"
    assert managed_claude["tui"] == "fullscreen"
    assert {config.dest for config in pi.configs if config.dest.startswith("pi/agent/")} == {
        "pi/agent/models.json",
        "pi/agent/web-search.json",
        "pi/agent/plannotator.json",
    }
    pi_settings = next(config for config in pi.configs if config.dest == "managed-settings/pi.json")
    assert pi_settings.mode == 0o600
    managed_pi = json.loads(pi_settings.content)
    assert managed_pi["defaultModel"] == "gpt-5.6-sol"
    assert managed_pi["defaultThinkingLevel"] == "high"
    assert managed_pi["theme"] == "light"
    angelini = next(vendor for vendor in pi.vendors if vendor.dest == "pi-angelini")
    assert angelini.source == _pi_angelini_root()
    assert len(pi.vendors) == 2


def test_agent_config_components_fail_clearly_for_missing_namespaces(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "missing-agent-config"
    (root / "settings").mkdir(parents=True)
    (root / "settings" / "claude.managed.json").write_text("{}\n")
    (root / "settings" / "pi.managed.json").write_text("{}\n")
    models = root / "pi" / "agent" / "models.json"
    models.parent.mkdir(parents=True)
    models.write_text("{}\n")
    monkeypatch.setenv("DOTGEN_AGENT_CONFIG_ROOT", str(root))
    claude_vendors = ClaudeCode().render(ENVIRONMENTS["macos"]).vendors
    pi_vendor = next(vendor for vendor in PiAgent().render(ENVIRONMENTS["macos"]).vendors if vendor.dest == "pi/agent")
    models.unlink()
    models.parent.rmdir()
    (root / "pi").rmdir()
    for vendor in (*claude_vendors, pi_vendor):
        with pytest.raises(FileNotFoundError, match=f"vendor source not found: {vendor.source}"):
            _vendor_dir(vendor, tmp_path / vendor.dest)


def test_vendor_deny_list_prunes_artifacts(tmp_path: Path) -> None:
    v = VendorDir(
        source=_VENDOR_SRC,
        dest="fx",
        exclude_dirs=GIT_ARTIFACTS | NODE_ARTIFACTS | PY_ARTIFACTS | BUILD_ARTIFACTS,
    )

    assert set(_vendored(v, tmp_path / "out")) == {
        "README.md",
        "logo.bin",
        "run.sh",
        "secrets.env",
        "pkg/index.ts",
        "pkg/foo.test.ts",
    }


def test_vendor_prunes_dir_names_by_glob() -> None:
    v = VendorDir(source=_VENDOR_SRC, dest="fx", exclude_dirs=PY_ARTIFACTS)

    assert v.prunes_dir("thing.egg-info")
    assert v.prunes_dir("__pycache__")
    assert not v.prunes_dir("thing")


def test_vendor_exclude_globs_match_basename_and_path(tmp_path: Path) -> None:
    v = VendorDir(
        source=_VENDOR_SRC,
        dest="fx",
        exclude_globs=("*.test.ts", "package-lock.json", "build/**"),
    )

    assert set(_vendored(v, tmp_path / "out")) == {
        ".gitignore",
        "README.md",
        "logo.bin",
        "run.sh",
        "secrets.env",
        "pkg/index.ts",
        "pkg/thing.egg-info",
        "pkg/build/inner.js",
        "pkg/node_modules/dep.js",
    }


def test_vendor_allow_list_mode_applies_deny_rules_on_top(tmp_path: Path) -> None:
    v = VendorDir(
        source=_VENDOR_SRC,
        dest="fx",
        exclude_globs=("*.test.ts", "build/**"),
        include_globs=("pkg/**", "README.md"),
    )

    kept = set(_vendored(v, tmp_path / "out"))

    assert kept == {
        "README.md",
        "pkg/index.ts",
        "pkg/package-lock.json",
        "pkg/thing.egg-info",
        "pkg/build/inner.js",
        "pkg/node_modules/dep.js",
    }
    assert "secrets.env" not in kept


def test_vendor_preserves_exec_bit(tmp_path: Path) -> None:
    out = tmp_path / "out"

    _vendor_dir(VendorDir(source=_VENDOR_SRC, dest="fx"), out)

    assert (out / "run.sh").stat().st_mode & 0o777 == 0o755
    assert (out / "README.md").stat().st_mode & 0o777 == 0o644


def test_vendor_forces_mode_when_not_preserving(tmp_path: Path) -> None:
    out = tmp_path / "out"

    _vendor_dir(VendorDir(source=_VENDOR_SRC, dest="fx", preserve_modes=False), out)

    assert (out / "run.sh").stat().st_mode & 0o777 == 0o644


def test_vendor_copies_binary_bytes(tmp_path: Path) -> None:
    out = tmp_path / "out"

    _vendor_dir(VendorDir(source=_VENDOR_SRC, dest="fx"), out)

    copied = (out / "logo.bin").read_bytes()
    assert copied == (_VENDOR_SRC / "logo.bin").read_bytes()
    assert b"\x00" in copied


def test_vendor_missing_source_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _vendor_dir(VendorDir(source=tmp_path / "nope", dest="fx"), tmp_path / "out")


def test_vendor_prunes_excluded_dirs_before_descent(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "node_modules" / "deep").mkdir(parents=True)
    (src / "node_modules" / "deep" / "dep.js").write_text("dep\n")
    (src / "keep.txt").write_text("keep\n")
    blocked = src / "node_modules"
    blocked.chmod(0o000)
    out = tmp_path / "out"
    try:
        _vendor_dir(VendorDir(source=src, dest="fx", exclude_dirs=NODE_ARTIFACTS), out)
    finally:
        blocked.chmod(0o755)

    assert {p.name for p in out.rglob("*")} == {"keep.txt"}


def test_vendor_unreadable_source_dir_raises(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "realdir").mkdir(parents=True)
    (src / "realdir" / "important.ts").write_text("important\n")
    (src / "keep.txt").write_text("keep\n")
    blocked = src / "realdir"
    blocked.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            _vendor_dir(VendorDir(source=src, dest="fx"), tmp_path / "out")
    finally:
        blocked.chmod(0o755)


def test_vendor_creates_dest_dir_when_filter_selects_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out"

    _vendor_dir(VendorDir(source=_VENDOR_SRC, dest="fx", include_globs=("no-such-path/**",)), out)

    assert out.is_dir()
    assert list(out.iterdir()) == []


def test_fragment_merge_concatenates_vendors() -> None:
    a = VendorDir(source=_VENDOR_SRC, dest="a")
    b = VendorDir(source=_VENDOR_SRC, dest="b")

    assert Fragment().merge(Fragment()).vendors == ()
    assert Fragment(vendors=(a,)).merge(Fragment()).vendors == (a,)
    assert Fragment().merge(Fragment(vendors=(b,))).vendors == (b,)
    assert Fragment(vendors=(a,)).merge(Fragment(vendors=(b,))).vendors == (a, b)
