import pytest

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
from dotgen.components.pi_agent import PiAgent
from dotgen.components.postgres import Postgres
from dotgen.components.python_tools import PythonTools
from dotgen.components.rust import Rust
from dotgen.components.starship import Starship
from dotgen.components.supacode import Supacode
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
        PiAgent,
    ],
)
def test_component_render_returns_fragment(env: Environment, cls: type[Component]) -> None:
    frag: Fragment = cls().render(env)
    assert isinstance(frag, Fragment)


@pytest.mark.parametrize("cls", [Rust, NodeFnm, GoLang, Gcloud, Aws, Fonts, Zed, Supacode, PiAgent])
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


def test_bash_base_macos_changes_shell_with_sudo() -> None:
    setup = BashBase().render(ENVIRONMENTS["macos"]).setup
    assert 'sudo chsh -s /opt/homebrew/bin/bash "$(whoami)"' in setup


def test_bash_base_flushes_history_and_updates_title() -> None:
    bashrc = BashBase().render(ENVIRONMENTS["macos"]).bashrc
    assert 'PROMPT_COMMAND="history -a;set_win_title;' in bashrc


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
    cfg = next(c for c in frag.configs if c.dest == "claude/settings.json")
    assert '"includeCoAuthoredBy": false' in cfg.content
    assert '"SessionStart"' in cfg.content
    assert "~/.claude/hooks/serena-reminder.sh" in cfg.content


def test_claude_code_emits_global_claude_md() -> None:
    frag = ClaudeCode().render(ENVIRONMENTS["macos"])
    cfg = next(c for c in frag.configs if c.dest == "claude/CLAUDE.md")
    assert "Always keep output concise" in cfg.content
    assert "Default to zero comments" in cfg.content
    assert "Serena" in cfg.content


def test_claude_code_emits_serena_hook_executable() -> None:
    frag = ClaudeCode().render(ENVIRONMENTS["macos"])
    hook = next(c for c in frag.configs if c.dest == "claude/hooks/serena-reminder.sh")
    assert hook.mode == 0o755
    assert hook.content.startswith("#!/usr/bin/env bash")
    assert "mcp__serena__initial_instructions" in hook.content


def test_claude_code_setup_installs_serena_via_uv_tool() -> None:
    setup = ClaudeCode().render(ENVIRONMENTS["macos"]).setup
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
        "go_lang",
        "gcloud",
        "aws",
        "fonts",
    }
    assert shared_names.issubset(debian_names & macos_names)
    assert {"ghostty", "zed", "supacode"}.isdisjoint(debian_names)
    assert {"ghostty", "zed", "supacode"}.issubset(macos_names)
    assert "node_fnm" in {c.name for c in ENVIRONMENTS["debian-docker"].components}


def test_node_precedes_pi_in_every_environment() -> None:
    for env in ENVIRONMENTS.values():
        names = [component.name for component in env.components]
        if "pi_agent" in names:
            assert names.index("node_fnm") < names.index("pi_agent")


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
    assert 'install_config "$DIR/config/pi/agent/settings.json" "$HOME/.pi/agent/settings.json"' in frag.setup
    assert 'install -m 0755 "$DIR/config/pi/sandbox/pi-sandbox.sh" "$HOME/.local/bin/pi-sandbox"' in frag.setup
    assert "GEMINI_API_KEY" in frag.secrets
    assert "EXA_API_KEY" in frag.secrets
    assert "CONTEXT7_API_KEY" in frag.secrets
    settings = next(cf for cf in frag.configs if cf.dest == "pi/agent/settings.json")
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
    assert "_install_pi_angelini" in frag.setup
    dests = {cf.dest for cf in frag.configs}
    assert {
        "pi/agent/settings.json",
        "pi/agent/models.json",
        "pi/agent/web-search.json",
        "pi/agent/AGENTS.md",
        "pi/agent/plannotator.json",
        "pi/agent/extensions/supacode/index.ts",
        "pi/agent/skills/supacode-cli/SKILL.md",
        "pi/agent/agents/claude-pipeline/architect.md",
        "pi/agent/agents/claude-pipeline/editor.md",
        "pi/agent/agents/claude-pipeline/planner.md",
        "pi/agent/agents/claude-pipeline/reviewer.md",
        "pi/agent/agents/claude-pipeline/scout.md",
        "pi/agent/chains/pipeline.chain.md",
        "pi/agent/prompts/pipeline.md",
        "pi/sandbox/pi-sandbox.sh",
        "pi/sandbox/pi-macos.sb",
        "pi-angelini/package.json",
        "pi-angelini/packages/editor-file-links/index.ts",
    }.issubset(dests)
    assert "pi-angelini/node_modules/package.json" not in dests
    assert "pi-angelini/packages/editor-file-links/.pi-lens/cache/review-graph.json" not in dests
    assert "pi-angelini/package-lock.json" not in dests
    agents_config = next(cf for cf in frag.configs if cf.dest == "pi/agent/AGENTS.md")
    assert "Do not use first-person phrasing in reasoning summaries or final responses." in agents_config.content
    assert "/simplify --staged" not in agents_config.content
    assert "Use subagents for reviewing, researching, planning and scouting code bases." in agents_config.content
    supacode = next(cf for cf in frag.configs if cf.dest == "pi/agent/extensions/supacode/index.ts")
    assert "OSC 3008" in supacode.content
    assert 'openSync("/dev/tty", "w")' in supacode.content


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
    assert '--bind "$HOME/.pi/agent" "$HOME/.pi/agent"' in script.content
    assert '--ro-bind-try "$HOME/.local/share/fnm" "$HOME/.local/share/fnm"' in script.content
    assert 'runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"' in script.content
    assert '--ro-bind-try "$runtime_dir/fnm_multishells" "$runtime_dir/fnm_multishells"' in script.content
    assert '--setenv XDG_RUNTIME_DIR "$runtime_dir"' in script.content
    assert "--unshare-net" not in script.content
    assert 'pi_bin="$(command -v pi)"' in script.content
    assert '"$pi_bin" "$@"' in script.content
    assert "GEMINI_API_KEY=${GEMINI_API_KEY:-}" in script.content
    assert "EXA_API_KEY=${EXA_API_KEY:-}" in script.content
    assert "CONTEXT7_API_KEY=${CONTEXT7_API_KEY:-}" in script.content
    assert '(allow file-read* file-write* (subpath (param "PI_AGENT")))' in profile.content
    assert "$HOME/.ssh" not in script.content
    assert '/.ssh"' in profile.content
    assert '"apiKey": "GEMINI_API_KEY"' in models.content
    assert "${GEMINI_API_KEY}" not in models.content
