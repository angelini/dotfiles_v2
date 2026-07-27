import os
import re
from pathlib import Path

import pytest

from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_env, config_manifest

GOLDEN_ROOT = Path(__file__).parent / "golden"
SNAPSHOT_FILES = ("setup.sh", "alias.sh", ".bashrc", "os_shim.sh")
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


@pytest.fixture(scope="module")
def built_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("snapshot")
    for name, env in ENVIRONMENTS.items():
        build_env(env, root / name)
    return root


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
@pytest.mark.parametrize("fname", SNAPSHOT_FILES)
def test_snapshot_matches_golden(built_root: Path, env_name: str, fname: str) -> None:
    actual = (built_root / env_name / fname).read_text()
    golden = GOLDEN_ROOT / env_name / fname

    if UPDATE or not golden.exists():
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual)
        if not UPDATE:
            pytest.skip(f"created missing golden {golden.relative_to(GOLDEN_ROOT.parent)}")
        return

    assert actual == golden.read_text(), f"snapshot drift for {env_name}/{fname}; re-run with UPDATE_GOLDEN=1 if intended"


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
def test_config_manifest_matches_golden(env_name: str) -> None:
    actual = config_manifest(ENVIRONMENTS[env_name])
    golden = GOLDEN_ROOT / env_name / "config-manifest.txt"

    if UPDATE or not golden.exists():
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual)
        if not UPDATE:
            pytest.skip(f"created missing golden {golden.relative_to(GOLDEN_ROOT.parent)}")
        return

    assert actual == golden.read_text(), f"config manifest drift for {env_name}; re-run with UPDATE_GOLDEN=1 if intended"


def test_agent_config_rendered_overlay_contract(built_root: Path) -> None:
    pi_call = 'install_config_dir "$DIR/config/pi/agent" "$HOME/.pi/agent" "pi-agent"'
    angelini_call = 'install_config_dir "$DIR/config/pi-angelini" "$HOME/repos/pi-angelini"'
    claude_call = 'install_config_dir "$DIR/config/claude" "$HOME/.claude" "claude"'
    pi_mutable = ("settings.json", "models.json", "web-search.json", "plannotator.json")

    for env_name in ENVIRONMENTS:
        root = built_root / env_name
        setup = (root / "setup.sh").read_text()
        manifest = config_manifest(ENVIRONMENTS[env_name])
        config = root / "config"

        assert setup.count(pi_call) == 1
        assert setup.count(angelini_call) == 1
        assert 'install_config "$DIR/config/pi/agent/' not in setup
        for name in pi_mutable:
            assert (config / "pi" / "agent" / name).is_file()
            assert f"  pi/agent/{name}" in manifest
        assert (config / "pi" / "agent" / "AGENTS.md").is_file()
        assert (config / "pi" / "agent" / "APPEND_SYSTEM.md").is_file()
        assert (config / "pi" / "sandbox" / "pi-sandbox.sh").is_file()
        assert (config / "pi" / "sandbox" / "pi-macos.sb").is_file()
        for path in ("auth.json", "sessions", "mcp-oauth", "extensions/context7/cache"):
            assert not (config / "pi" / "agent" / path).exists()
        assert manifest.count("dir  pi/agent") == 1
        assert manifest.count("dir  pi-angelini") == 1
        for path in (
            "AGENTS.md",
            "agents/claude-pipeline/reviewer.md",
            "chains/pipeline.chain.md",
            "prompts/pipeline.md",
            "extensions/supacode/index.ts",
            "skills/pipeline/SKILL.md",
            "skills/supacode-cli/SKILL.md",
        ):
            assert f"  pi/agent/{path}" not in manifest

        if env_name in ("debian", "macos"):
            assert setup.count(claude_call) == 1
            assert 'install_config "$DIR/config/claude/CLAUDE.md"' not in setup
            assert 'install_config "$DIR/config/claude/hooks/' not in setup
            assert 'chmod +x "$HOME/.claude/hooks/' not in setup
            assert "install_script claude https://claude.ai/install.sh" in setup
            assert "tool install --from https://github.com/oraios/serena/archive/refs/heads/main.tar.gz serena-agent" in setup
            assert "claude mcp add serena -s user -- serena start-mcp-server --context claude-code" in setup
            assert 'install_config "$DIR/config/claude/settings.json"' in setup
            assert (config / "claude" / "settings.json").is_file()
            assert (config / "claude" / "CLAUDE.md").is_file()
            for path in ("agents", "commands", "hooks", "skills"):
                assert (config / "claude" / path).is_dir()
            for path in (".credentials.json", "history.jsonl", "projects"):
                assert not (config / "claude" / path).exists()
            assert manifest.count("dir  claude") == 1
            assert "  claude/settings.json" in manifest
            assert "  claude/CLAUDE.md" not in manifest
            assert "  claude/hooks/" not in manifest
        else:
            assert claude_call not in setup
            assert "dir  claude" not in manifest

    assert "claude" != "pi-agent"
    for env_name in ENVIRONMENTS:
        setup = (built_root / env_name / "setup.sh").read_text()
        assert 'install_config_dir "$DIR/config/pi-angelini" "$HOME/repos/pi-angelini" "' not in setup


_HEADER_RE = re.compile(r"^# --- ([a-z_][a-z_0-9]*) ---$", re.MULTILINE)


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
@pytest.mark.parametrize("fname", ("setup.sh", "alias.sh", ".bashrc"))
def test_chunk_headers_match_registered_components(built_root: Path, env_name: str, fname: str) -> None:
    text = (built_root / env_name / fname).read_text()
    found = _HEADER_RE.findall(text)
    valid = {c.name for c in ENVIRONMENTS[env_name].components}
    unknown = [name for name in found if name not in valid]
    assert not unknown, f"unknown component headers in {env_name}/{fname}: {unknown}"


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
def test_setup_header_pairs_with_component_begin(built_root: Path, env_name: str) -> None:
    text = (built_root / env_name / "setup.sh").read_text()
    for match in _HEADER_RE.finditer(text):
        name = match.group(1)
        tail = text[match.end() :]
        next_line = tail.lstrip("\n").split("\n", 1)[0]
        assert next_line == f'component_begin "{name}"', f"expected component_begin after `# --- {name} ---` in setup.sh, got {next_line!r}"


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
@pytest.mark.parametrize("fname", ("setup.sh", "alias.sh", ".bashrc"))
def test_chunks_separated_by_blank_line(built_root: Path, env_name: str, fname: str) -> None:
    text = (built_root / env_name / fname).read_text()
    headers = list(_HEADER_RE.finditer(text))
    for header in headers[1:]:
        preceding = text[: header.start()]
        assert preceding.endswith("\n\n"), f"{env_name}/{fname}: header `{header.group(0)}` is not preceded by a blank line"
