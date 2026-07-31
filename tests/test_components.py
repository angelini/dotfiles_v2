import json
from pathlib import Path

import pytest

from dotgen.component import Component
from dotgen.components import agent_config as agent_config_module
from dotgen.components.agent_config import _agent_config_root, managed_settings  # pyright: ignore[reportPrivateUsage]
from dotgen.components.aws import Aws
from dotgen.components.bash_base import BashBase
from dotgen.components.claude_code import ClaudeCode
from dotgen.components.core_utils import CoreUtils
from dotgen.components.docker import Docker
from dotgen.components.doppler import Doppler
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
from dotgen.components.mosh import Mosh
from dotgen.components.node_fnm import NodeFnm
from dotgen.components.npm_config import NpmConfig
from dotgen.components.pi_agent import SANDBOX_HOME_POLICY, PiAgent, _pi_angelini_root  # pyright: ignore[reportPrivateUsage]
from dotgen.components.postgres import Postgres
from dotgen.components.python_tools import PythonTools
from dotgen.components.rust import Rust
from dotgen.components.starship import Starship
from dotgen.components.stinkpot import Stinkpot
from dotgen.components.supacode import Supacode
from dotgen.components.tmux import Tmux
from dotgen.components.zed import Zed
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
        Stinkpot,
        Tmux,
        Mosh,
        GitSetup,
        Helix,
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


@pytest.mark.parametrize("cls", [Rust, NodeFnm, GoLang, Gcloud, Aws, Doppler, Fonts, Zed, Supacode, PiAgent])
def test_addon_component_renders_for_supported_oses(cls: type[Component]) -> None:
    for env_name in ("macos", "debian", "debian-docker"):
        env = ENVIRONMENTS[env_name]
        comp = cls()
        if comp.applies_to(env):
            assert isinstance(comp.render(env), Fragment)


def test_bash_base_ls_alias_per_os() -> None:
    mac = BashBase().render(ENVIRONMENTS["macos"]).alias
    linux = BashBase().render(ENVIRONMENTS["debian"]).alias
    assert "ls -hlAG" in mac
    assert "--color=auto" in linux


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


def test_bash_base_macos_changes_shell_with_sudo() -> None:
    setup = BashBase().render(ENVIRONMENTS["macos"]).setup
    assert 'sudo chsh -s /opt/homebrew/bin/bash "$(whoami)"' in setup


def test_bash_base_uses_only_in_memory_history_and_updates_title() -> None:
    bashrc = BashBase().render(ENVIRONMENTS["macos"]).bashrc
    for forbidden in ("HISTSIZE", "HISTFILESIZE", "HISTCONTROL", "histappend", "history -a"):
        assert forbidden not in bashrc
    assert "set_win_title" in bashrc
    assert "PROMPT_COMMAND" in bashrc


def test_core_utils_per_os_fd_token() -> None:
    debian = CoreUtils().render(ENVIRONMENTS["debian"]).setup
    macos = CoreUtils().render(ENVIRONMENTS["macos"]).setup
    assert "fd-find" in debian
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
    assert 'theme = "github_light"' in cfg
    assert 'normal = "block"' in cfg
    assert 'select = "underline"' in cfg
    assert "[editor.file-picker]" in cfg
    assert "hidden = false" in cfg
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
    assert "install_packages kubectl helm k9s kubectx" in macos
    assert "_install_helm_linux" not in macos
    assert "add_repo" not in debian
    assert "_install_kubectl_linux" in debian
    assert "_install_helm_linux" in debian
    assert "_install_k9s_linux" in debian
    assert "_install_kubectx_linux" in debian
    assert "_install_kubens_linux" in debian
    assert "https://dl.k8s.io/release/v1.35.4/bin/linux/" in debian
    assert "helm-v3.20.2-linux-" in debian
    assert "kubectx/releases/download/v0.11.0/kubectx_v0.11.0_linux_" in debian
    assert "kubectx/releases/download/v0.11.0/kubens_v0.11.0_linux_" in debian
    assert "kubie/releases/download/v0.27.0/kubie-linux-" in debian
    assert "kubie generate-completion" in Kubectl().render(ENVIRONMENTS["debian"]).bashrc


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
    assert 'install_config "$DIR/config/claude/settings.json" "$HOME/.claude/settings.json"' not in setup
    assert 'install_config "$DIR/config/claude/CLAUDE.md"' not in setup
    assert 'install_config "$DIR/config/claude/hooks/serena-reminder.sh"' not in setup
    assert "chmod" not in setup
    assert "tool install --from https://github.com/oraios/serena/archive/refs/heads/main.tar.gz serena-agent" in setup
    assert "claude mcp add serena" in setup


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
    for s in (debian, macos):
        assert "install_script uv https://astral.sh/uv/install.sh" in s


def test_go_lang_only_macos() -> None:
    assert GoLang().applies_to(ENVIRONMENTS["debian"])
    assert GoLang().applies_to(ENVIRONMENTS["macos"])
    assert 'GO_VERSION="1.25.5"' in GoLang().render(ENVIRONMENTS["macos"]).setup


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
        "stinkpot",
        "tmux",
        "mosh",
        "helix",
        "starship",
        "zoxide",
        "kubectl",
        "python_tools",
        "claude_code",
        "gh",
        "git_signing",
        "rust",
        "node_fnm",
        "npm_config",
        "go_lang",
        "gcloud",
        "aws",
        "doppler",
        "fonts",
    }
    assert shared_names.issubset(debian_names & macos_names)
    assert {"ghostty", "zed", "supacode"}.isdisjoint(debian_names)
    assert {"ghostty", "zed", "supacode"}.issubset(macos_names)
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
    assert macos == "install_packages gnupg dopplerhq/cli/doppler\n"


def test_docker_is_full_debian_only_and_ordered_before_final_deployers() -> None:
    assert Docker().applies_to(ENVIRONMENTS["debian"])
    assert not Docker().applies_to(ENVIRONMENTS["debian-docker"])
    assert not Docker().applies_to(ENVIRONMENTS["macos"])
    for name in ("debian-docker", "macos"):
        assert "docker" not in [component.name for component in ENVIRONMENTS[name].components]
    names = [component.name for component in ENVIRONMENTS["debian"].components]
    assert names.count("docker") == 1
    assert names[-4:] == ["fonts", "docker", "git_setup", "dotfiles_deploy"]


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
    assert "shell-integration-features = ssh-env,ssh-terminfo" in cfg
    assert "scrollback-limit = 100_000_000" in cfg
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


def test_zed_macos_only_and_emits_configs() -> None:
    debian_names = {c.name for c in ENVIRONMENTS["debian"].components}
    assert "zed" not in debian_names
    frag = Zed().render(ENVIRONMENTS["macos"])
    dests = sorted(c.dest for c in frag.configs)
    assert dests == ["zed/keymap.json", "zed/settings.json"]
    settings = next(c for c in frag.configs if c.dest == "zed/settings.json").content
    assert '"cli_default_open_behavior": "new_window"' in settings
    assert '"diff_view_style": "unified"' in settings
    assert '"**/deploy/helm/templates/**/*.yaml"' in settings
    macos = Zed().render(ENVIRONMENTS["macos"]).setup
    assert "install_cask zed" in macos


def test_supacode_macos_only_and_installs_cask() -> None:
    assert Supacode().applies_to(ENVIRONMENTS["macos"])
    assert not Supacode().applies_to(ENVIRONMENTS["debian"])
    assert "install_cask supacode" in Supacode().render(ENVIRONMENTS["macos"]).setup


def test_install_script_used_for_curl_installers() -> None:
    expected = {
        "starship": "install_script starship https://starship.rs/install.sh -y",
        "rust": "install_script cargo https://sh.rustup.rs -y --default-toolchain stable",
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


def test_node_fnm_activates_latest_lts_during_deploy() -> None:
    frag = NodeFnm().render(ENVIRONMENTS["debian"])
    assert 'if [ "$DOTGEN_MODE" = deploy ]; then' in frag.setup
    assert 'fnm_bin="$HOME/.local/share/fnm/fnm"' in frag.setup
    assert "exit 1" in frag.setup
    assert 'eval "$("$fnm_bin" env --shell bash)"' in frag.setup
    assert '"$fnm_bin" install --lts --use' in frag.setup
    assert 'eval "$(fnm env --use-on-cd --shell bash)"' in frag.bashrc


def test_dotfiles_deploy_emits_bashrc_and_alias_install() -> None:
    for env_name in ("debian", "macos"):
        setup = DotfilesDeploy().render(ENVIRONMENTS[env_name]).setup
        assert 'install_config "$DIR/.bashrc" "$HOME/.bashrc"' in setup
        assert 'install_config "$DIR/alias.sh" "$HOME/.aliases"' in setup


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
    assert "install_npm_global @earendil-works/pi-coding-agent" in frag.setup
    assert "install_npm_global pi-lens" in frag.setup
    assert "install_npm_global @plannotator/pi-extension" in frag.setup
    assert "install_npm_global @dreki-gg/pi-context7" in frag.setup
    assert "install_npm_global @juicesharp/rpiv-btw" in frag.setup
    assert "install_npm_global @vanillagreen/pi-web-tools" in frag.setup
    assert "install_npm_global pi-web-access" not in frag.setup
    assert 'install_config_dir "$DIR/config/pi/agent" "$HOME/.pi/agent" "pi-agent" "settings.json"' in frag.setup
    assert 'install_json_patch "$DIR/config/managed-settings/pi.json" "$HOME/.pi/agent/settings.json" 0600' in frag.setup
    assert 'install -m 0755 "$DIR/config/pi/sandbox/pi-sandbox.sh" "$HOME/.local/bin/pi-sandbox"' in frag.setup
    assert "GEMINI_API_KEY" in frag.secrets
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
        "pi/sandbox/pi-sandbox.sh",
        "pi/sandbox/pi-macos.sb",
    }
    assert not [d for d in dests if d.startswith("pi-angelini/")]
    agent_vendor, angelini_vendor = frag.vendors
    assert agent_vendor.source == _agent_config_root() / "pi" / "agent"
    assert agent_vendor.dest == "pi/agent"
    assert agent_vendor.include_globs == (
        "AGENTS.md",
        "APPEND_SYSTEM.md",
        "agents/claude-pipeline/*.md",
        "chains/pipeline.chain.md",
        "extensions/supacode/index.ts",
        "prompts/pipeline.md",
        "skills/pipeline/**",
        "skills/supacode-cli/**",
    )
    assert angelini_vendor.source == _pi_angelini_root()
    assert angelini_vendor.dest == "pi-angelini"
    assert angelini_vendor.exclude_dirs == GIT_ARTIFACTS | NODE_ARTIFACTS | PY_ARTIFACTS | frozenset({".pi-lens", ".pi-subagents", ".serena", "dist"})
    assert angelini_vendor.exclude_globs == ("package-lock.json", "pi-system-audit-plan.md", "*.test.ts")


def test_pi_agent_sandbox_aliases() -> None:
    frag = PiAgent().render(ENVIRONMENTS["macos"])
    assert 'pi-sandbox "$@"' in frag.alias
    assert 'command pi "$@"' in frag.alias


def test_pi_agent_bubblewrap_linux_only() -> None:
    assert "install_package bubblewrap" in PiAgent().render(ENVIRONMENTS["debian"]).setup
    assert "install_package bubblewrap" not in PiAgent().render(ENVIRONMENTS["macos"]).setup


def test_pi_agent_sandbox_configs() -> None:
    frag = PiAgent().render(ENVIRONMENTS["macos"])
    script = next(cf for cf in frag.configs if cf.dest == "pi/sandbox/pi-sandbox.sh")
    profile = next(cf for cf in frag.configs if cf.dest == "pi/sandbox/pi-macos.sb")
    models = next(cf for cf in frag.configs if cf.dest == "pi/agent/models.json")
    assert script.mode == 0o755
    assert {
        ".ssh",
        ".gnupg",
        ".aws",
        ".azure",
        ".config/dotgen",
        ".config/gcloud",
        ".kube",
    } <= set(SANDBOX_HOME_POLICY.hidden_dirs)
    assert ".local/share/stinkpot" in SANDBOX_HOME_POLICY.hidden_dirs
    assert ".local/share/stinkpot" not in SANDBOX_HOME_POLICY.hidden_files
    assert ".local/share" in SANDBOX_HOME_POLICY.writable_dirs
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

    assert 'transformers_cache="$memory_dir/transformers-cache"' in script.content
    assert 'transformers_cache_target="$(npm root -g)/@samfp/pi-memory/' in script.content
    fnm_bind = '--ro-bind "$HOME/.local/share/fnm" "$HOME/.local/share/fnm"'
    cache_bind = '--bind "$transformers_cache" "$transformers_cache_target"'
    assert script.content.index(fnm_bind) < script.content.index(cache_bind)
    assert '-D "TRANSFORMERS_CACHE=$transformers_cache_target"' in script.content
    assert '(subpath (param "TRANSFORMERS_CACHE"))' in profile.content
    assert 'runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"' in script.content
    assert '--ro-bind-try "$runtime_dir/fnm_multishells" "$runtime_dir/fnm_multishells"' in script.content
    assert '--setenv XDG_RUNTIME_DIR "$runtime_dir"' in script.content
    assert "--unshare-net" not in script.content
    assert 'pi_bin="$(command -v pi)"' in script.content
    assert '"$pi_bin" "$@"' in script.content
    assert "GEMINI_API_KEY=${GEMINI_API_KEY:-}" in script.content
    assert "EXA_API_KEY=${EXA_API_KEY:-}" in script.content
    assert "CONTEXT7_API_KEY=${CONTEXT7_API_KEY:-}" in script.content
    assert "__SANDBOX_" not in script.content
    assert "__MACOS_" not in profile.content
    assert '"apiKey": "GEMINI_API_KEY"' in models.content
    assert "${GEMINI_API_KEY}" not in models.content


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
    (claude_vendor,) = claude.vendors
    pi_vendor = next(vendor for vendor in pi.vendors if vendor.dest == "pi/agent")

    assert claude_vendor.source == _AGENT_CONFIG_SRC / "claude"
    assert claude_vendor.dest == "claude"
    assert claude_vendor.include_globs == ("CLAUDE.md", "agents/*.md", "commands/review.md", "hooks/*", "skills/**")
    assert pi_vendor.source == _AGENT_CONFIG_SRC / "pi" / "agent"
    assert pi_vendor.dest == "pi/agent"
    assert pi_vendor.include_globs == (
        "AGENTS.md",
        "APPEND_SYSTEM.md",
        "agents/claude-pipeline/*.md",
        "chains/pipeline.chain.md",
        "extensions/supacode/index.ts",
        "prompts/pipeline.md",
        "skills/pipeline/**",
        "skills/supacode-cli/**",
    )
    assert set(_vendored(claude_vendor, tmp_path / "claude")) == {
        "CLAUDE.md",
        "agents/reviewer.md",
        "commands/review.md",
        "hooks/fixture-hook.sh",
        "skills/fixture/SKILL.md",
    }
    assert set(_vendored(pi_vendor, tmp_path / "pi")) == {
        "AGENTS.md",
        "APPEND_SYSTEM.md",
        "agents/claude-pipeline/reviewer.md",
        "chains/pipeline.chain.md",
        "extensions/supacode/index.ts",
        "prompts/pipeline.md",
        "skills/pipeline/SKILL.md",
        "skills/supacode-cli/SKILL.md",
    }
    assert "README.md" not in _vendored(claude_vendor, tmp_path / "claude-again")
    assert "extensions/context7/cache/generated.json" not in _vendored(pi_vendor, tmp_path / "pi-again")
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
    monkeypatch.setenv("DOTGEN_AGENT_CONFIG_ROOT", str(root))
    claude_vendor = ClaudeCode().render(ENVIRONMENTS["macos"]).vendors[0]
    pi_vendor = next(vendor for vendor in PiAgent().render(ENVIRONMENTS["macos"]).vendors if vendor.dest == "pi/agent")
    for vendor in (claude_vendor, pi_vendor):
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
