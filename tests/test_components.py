import pytest

from dotgen.components.aws import Aws
from dotgen.components.bash_base import BashBase
from dotgen.components.claude_code import ClaudeCode
from dotgen.components.core_utils import CoreUtils
from dotgen.components.dotfiles_deploy import DotfilesDeploy
from dotgen.components.gcloud import Gcloud
from dotgen.components.gh import Gh
from dotgen.components.ghostty import Ghostty
from dotgen.components.git_setup import GitSetup
from dotgen.components.git_signing import GitSigning
from dotgen.components.go_lang import GoLang
from dotgen.components.helix import Helix
from dotgen.components.kubectl import Kubectl
from dotgen.components.node_fnm import NodeFnm
from dotgen.components.postgres import Postgres
from dotgen.components.python_tools import PythonTools
from dotgen.components.rust import Rust
from dotgen.components.starship import Starship
from dotgen.components.zed import Zed
from dotgen.components.zoxide import Zoxide
from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.registry import ENVIRONMENTS


@pytest.fixture(params=list(ENVIRONMENTS.values()), ids=list(ENVIRONMENTS))
def env(request: pytest.FixtureRequest) -> Environment:
    return request.param


@pytest.mark.parametrize(
    "cls",
    [
        BashBase,
        CoreUtils,
        GitSetup,
        Helix,
        Starship,
        Zoxide,
        Kubectl,
        ClaudeCode,
        PythonTools,
        Gh,
        GitSigning,
    ],
)
def test_component_render_returns_fragment(env: Environment, cls) -> None:
    frag = cls().render(env)
    assert isinstance(frag, Fragment)


@pytest.mark.parametrize("cls", [Rust, NodeFnm, GoLang, Gcloud, Aws, Zed])
def test_addon_component_renders_for_supported_oses(cls) -> None:
    for env_name in ("fedora", "macos"):
        env = ENVIRONMENTS[env_name]
        comp = cls()
        if comp.applies_to(env):
            assert isinstance(comp.render(env), Fragment)


def test_bash_base_ls_alias_per_os() -> None:
    mac = BashBase().render(ENVIRONMENTS["macos"]).alias
    linux = BashBase().render(ENVIRONMENTS["debian"]).alias
    assert "ls -hlAG" in mac
    assert "--color=auto" in linux


def test_core_utils_per_os_fd_token() -> None:
    debian = CoreUtils().render(ENVIRONMENTS["debian"]).setup
    fedora = CoreUtils().render(ENVIRONMENTS["fedora"]).setup
    macos = CoreUtils().render(ENVIRONMENTS["macos"]).setup
    assert "fd-find" in debian
    assert "fd-find" in fedora
    assert " fd " in macos and "fd-find" not in macos


def test_core_utils_debian_adds_fd_symlink() -> None:
    setup = CoreUtils().render(ENVIRONMENTS["debian"]).setup
    assert "fdfind" in setup and "ln -sf" in setup


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


def test_git_setup_signs_with_ssh_key() -> None:
    cfg = next(c for c in GitSetup().render(ENVIRONMENTS["macos"]).configs if c.dest == "git/gitconfig").content
    assert "format = ssh" in cfg
    assert "signingkey = ~/.ssh/id_signing.pub" in cfg
    assert "gpgsign = true" in cfg


def test_git_signing_uploads_via_gh() -> None:
    setup = GitSigning().render(ENVIRONMENTS["macos"]).setup
    assert "ssh-keygen -t ed25519" in setup
    assert "id_signing" in setup
    assert "gh ssh-key add" in setup
    assert "--type signing" in setup


def test_helix_emits_config_and_editor_env(env: Environment) -> None:
    frag = Helix().render(env)
    assert any(c.dest == "helix/config.toml" for c in frag.configs)
    assert "EDITOR=hx" in frag.bashrc


def test_starship_emits_config_and_init() -> None:
    frag = Starship().render(ENVIRONMENTS["macos"])
    assert any(c.dest == "starship/starship.toml" for c in frag.configs)
    assert "starship init bash" in frag.bashrc
    cfg = next(c for c in frag.configs if c.dest == "starship/starship.toml").content
    assert "[kubernetes]" in cfg
    assert "context_pattern" in cfg
    for disabled in ("[gcloud]", "[aws]", "[docker_context]", "[dotnet]"):
        assert disabled in cfg


def test_kubectl_per_os_branching() -> None:
    macos = Kubectl().render(ENVIRONMENTS["macos"]).setup
    debian = Kubectl().render(ENVIRONMENTS["debian"]).setup
    fedora = Kubectl().render(ENVIRONMENTS["fedora"]).setup
    assert "install_packages kubectl helm k9s kubectx" in macos
    assert "_install_helm_linux" not in macos
    assert "add_repo" not in debian and "add_repo" not in fedora
    for body in (debian, fedora):
        assert "_install_kubectl_linux" in body
        assert "_install_helm_linux" in body
        assert "_install_k9s_linux" in body
        assert "_install_kubectx_linux" in body
        assert "_install_kubens_linux" in body
        assert "https://dl.k8s.io/release/v1.35.4/bin/linux/" in body
        assert "helm-v3.20.2-linux-" in body
        assert "kubectx/releases/download/v0.11.0/kubectx_v0.11.0_linux_" in body
        assert "kubectx/releases/download/v0.11.0/kubens_v0.11.0_linux_" in body


def test_claude_code_settings() -> None:
    frag = ClaudeCode().render(ENVIRONMENTS["macos"])
    cfg = next(c for c in frag.configs if c.dest == "claude/settings.json")
    assert '"includeCoAuthoredBy": false' in cfg.content
    assert '"SessionStart"' in cfg.content
    assert "~/.claude/hooks/serena-reminder.sh" in cfg.content


def test_claude_code_emits_global_claude_md() -> None:
    frag = ClaudeCode().render(ENVIRONMENTS["macos"])
    cfg = next(c for c in frag.configs if c.dest == "claude/CLAUDE.md")
    assert "Rules for generating responses" in cfg.content
    assert "Serena" in cfg.content


def test_claude_code_emits_serena_hook_executable() -> None:
    frag = ClaudeCode().render(ENVIRONMENTS["macos"])
    hook = next(c for c in frag.configs if c.dest == "claude/hooks/serena-reminder.sh")
    assert hook.mode == 0o755
    assert hook.content.startswith("#!/usr/bin/env bash")
    assert "mcp__serena__initial_instructions" in hook.content


def test_claude_code_setup_installs_serena_via_uv_tool() -> None:
    setup = ClaudeCode().render(ENVIRONMENTS["macos"]).setup
    assert (
        "tool install --from https://github.com/oraios/serena/archive/refs/heads/main.tar.gz serena-agent"
        in setup
    )
    assert "claude mcp add serena" in setup


def test_claude_code_runs_after_python_tools() -> None:
    for env in ENVIRONMENTS.values():
        names = [c.name for c in env.components]
        assert names.index("python_tools") < names.index("claude_code"), f"{env.name}: claude_code must follow python_tools so uv is available"


def test_python_tools_per_os_build_deps() -> None:
    debian = PythonTools().render(ENVIRONMENTS["debian"]).setup
    fedora = PythonTools().render(ENVIRONMENTS["fedora"]).setup
    macos = PythonTools().render(ENVIRONMENTS["macos"]).setup
    assert "build-essential" in debian
    assert "openssl-devel" in fedora
    assert "install_packages" not in macos.split("install_script uv")[0]
    for s in (debian, fedora, macos):
        assert "install_script uv https://astral.sh/uv/install.sh" in s


def test_go_lang_only_fedora_macos() -> None:
    assert not GoLang().applies_to(ENVIRONMENTS["debian"])
    assert GoLang().applies_to(ENVIRONMENTS["fedora"])
    assert GoLang().applies_to(ENVIRONMENTS["macos"])


def test_aws_emits_config_with_secure_mode() -> None:
    frag = Aws().render(ENVIRONMENTS["macos"])
    cfg = next(c for c in frag.configs if c.dest == "aws/config")
    assert cfg.mode == 0o600
    assert "[default]" in cfg.content


def test_environment_component_distribution() -> None:
    debian_names = {c.name for c in ENVIRONMENTS["debian"].components}
    fedora_names = {c.name for c in ENVIRONMENTS["fedora"].components}
    macos_names = {c.name for c in ENVIRONMENTS["macos"].components}
    full_only = {"rust", "node_fnm", "go_lang", "gcloud", "aws", "zed"}
    assert full_only.isdisjoint(debian_names)
    assert full_only.issubset(fedora_names)
    assert "ghostty" in macos_names
    assert "ghostty" not in debian_names | fedora_names


def test_ghostty_macos_only_and_emits_config() -> None:
    assert Ghostty().applies_to(ENVIRONMENTS["macos"])
    assert not Ghostty().applies_to(ENVIRONMENTS["debian"])
    assert not Ghostty().applies_to(ENVIRONMENTS["fedora"])
    frag = Ghostty().render(ENVIRONMENTS["macos"])
    assert any(c.dest == "ghostty/config" for c in frag.configs)
    assert "install_cask ghostty" in frag.setup
    assert "Library/Application Support/com.mitchellh.ghostty" in frag.setup


def test_gh_emits_config_in_every_env() -> None:
    for env_name in ("debian", "fedora", "macos"):
        frag = Gh().render(ENVIRONMENTS[env_name])
        assert any(c.dest == "gh/config.yml" for c in frag.configs)
        assert "co: pr checkout" in next(c for c in frag.configs if c.dest == "gh/config.yml").content


def test_gh_per_os_install() -> None:
    debian = Gh().render(ENVIRONMENTS["debian"]).setup
    fedora = Gh().render(ENVIRONMENTS["fedora"]).setup
    macos = Gh().render(ENVIRONMENTS["macos"]).setup
    assert "add_repo apt githubcli" in debian and "install_package gh" in debian
    assert "install_package gh" in fedora and "add_repo" not in fedora
    assert "install_package gh" in macos and "add_repo" not in macos


def test_zed_fedora_macos_only_and_emits_configs() -> None:
    debian_names = {c.name for c in ENVIRONMENTS["debian"].components}
    assert "zed" not in debian_names
    for env_name in ("fedora", "macos"):
        frag = Zed().render(ENVIRONMENTS[env_name])
        dests = sorted(c.dest for c in frag.configs)
        assert dests == ["zed/keymap.json", "zed/settings.json"]
    macos = Zed().render(ENVIRONMENTS["macos"]).setup
    fedora = Zed().render(ENVIRONMENTS["fedora"]).setup
    assert "install_cask zed" in macos
    assert "install_script zed https://zed.dev/install.sh" in fedora


def test_install_script_used_for_curl_installers() -> None:
    expected = {
        "starship": "install_script starship https://starship.rs/install.sh -y",
        "rust": "install_script cargo https://sh.rustup.rs -y --default-toolchain stable",
        "node_fnm": "install_script fnm https://fnm.vercel.app/install --skip-shell",
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


def test_dotfiles_deploy_emits_bashrc_and_alias_install() -> None:
    for env_name in ("debian", "fedora", "macos"):
        setup = DotfilesDeploy().render(ENVIRONMENTS[env_name]).setup
        assert 'install_config "$DIR/.bashrc" "$HOME/.bashrc"' in setup
        assert 'install_config "$DIR/alias.sh" "$HOME/.aliases"' in setup


def test_dotfiles_deploy_runs_last_in_every_env() -> None:
    for env in ENVIRONMENTS.values():
        assert env.components[-1].name == "dotfiles_deploy", f"{env.name}: dotfiles_deploy must run last"


def test_postgres_unwired_but_renders_per_os() -> None:
    for env_name in ("debian", "fedora", "macos"):
        env = ENVIRONMENTS[env_name]
        names = {c.name for c in env.components}
        assert "postgres" not in names, "postgres must stay opt-in"
        frag = Postgres().render(env)
        assert frag.bashrc and "PATH" in frag.bashrc
    mac = Postgres().render(ENVIRONMENTS["macos"]).setup
    deb = Postgres().render(ENVIRONMENTS["debian"]).setup
    fed = Postgres().render(ENVIRONMENTS["fedora"]).setup
    assert "install_package postgresql@18" in mac
    assert "add_repo apt pgdg" in deb and "postgresql-18" in deb
    assert "add_repo dnf pgdg18" in fed and "postgresql18-server" in fed
