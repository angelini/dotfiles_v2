import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

from dotgen.artifact import FakeArtifactBuilder
from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_env, config_manifest

GOLDEN_ROOT = Path(__file__).parent / "golden"
SNAPSHOT_FILES = ("setup.sh", "alias.sh", ".bashrc", "os_shim.sh")
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


@pytest.fixture(scope="module")
def built_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("snapshot")
    builder = FakeArtifactBuilder()
    for name, env in ENVIRONMENTS.items():
        build_env(env, root / name, artifact_builder=builder)
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
    pi_call = 'install_config_dir "$DIR/config/pi/agent" "$HOME/.pi/agent" "pi-agent" "settings.json"'
    pi_patch_call = 'install_json_patch "$DIR/config/managed-settings/pi.json" "$HOME/.pi/agent/settings.json" 0600'
    angelini_call = 'install_config_dir "$DIR/config/pi-angelini" "$HOME/repos/pi-angelini"'
    claude_call = 'install_config_dir "$DIR/config/claude" "$HOME/.claude" "claude" "settings.json"'
    claude_patch_call = 'install_json_patch "$DIR/config/managed-settings/claude.json" "$HOME/.claude/settings.json" 0600'
    platform_call = 'install_config "$DIR/config/repositories/platform/CLAUDE.md" "$HOME/repos/platform/CLAUDE.md"'
    pi_mutable = ("models.json", "web-search.json")

    for env_name in ENVIRONMENTS:
        root = built_root / env_name
        setup = (root / "setup.sh").read_text()
        manifest = config_manifest(ENVIRONMENTS[env_name])
        config = root / "config"

        assert setup.count(pi_call) == 1
        assert setup.count(pi_patch_call) == 1
        assert setup.count(angelini_call) == 1
        assert 'install_config "$DIR/config/pi/agent/' not in setup
        for name in pi_mutable:
            assert (config / "pi" / "agent" / name).is_file()
            assert f"  pi/agent/{name}" in manifest
        assert not (config / "pi" / "agent" / "settings.json").exists()
        pi_managed_patch = config / "managed-settings" / "pi.json"
        assert pi_managed_patch.is_file()
        assert pi_managed_patch.stat().st_mode & 0o777 == 0o600
        assert "  managed-settings/pi.json" in manifest
        assert "  pi/agent/settings.json" not in manifest
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
            "skills/pipeline/SKILL.md",
        ):
            assert f"  pi/agent/{path}" not in manifest
        assert not (config / "pi" / "agent" / "extensions" / "supacode").exists()
        assert not (config / "pi" / "agent" / "skills" / "supacode-cli").exists()
        assert "supacode" not in manifest.lower()

        if env_name in ("debian", "macos"):
            assert setup.count(claude_call) == 1
            assert 'install_config "$DIR/config/claude/CLAUDE.md"' not in setup
            assert 'install_config "$DIR/config/claude/hooks/' not in setup
            assert 'chmod +x "$HOME/.claude/hooks/' not in setup
            assert "install_script claude https://claude.ai/install.sh" in setup
            assert "tool install --from https://github.com/oraios/serena/archive/refs/heads/main.tar.gz serena-agent" in setup
            assert "claude mcp add serena -s user -- serena start-mcp-server --context claude-code" in setup
            assert setup.count(claude_patch_call) == 1
            assert setup.count(platform_call) == 1
            assert 'install_config "$DIR/config/claude/settings.json"' not in setup
            assert not (config / "claude" / "settings.json").exists()
            managed_patch = config / "managed-settings" / "claude.json"
            assert managed_patch.is_file()
            assert managed_patch.stat().st_mode & 0o777 == 0o600
            assert (config / "claude" / "CLAUDE.md").is_file()
            for path in ("agents", "commands", "hooks", "skills"):
                assert (config / "claude" / path).is_dir()
            for path in (".credentials.json", "history.jsonl", "projects"):
                assert not (config / "claude" / path).exists()
            platform_instructions = config / "repositories" / "platform" / "CLAUDE.md"
            canonical_instructions = Path(__file__).resolve().parents[2] / "agent-config" / "repositories" / "platform" / "CLAUDE.md"
            assert platform_instructions.read_bytes() == canonical_instructions.read_bytes()
            assert manifest.count("dir  claude") == 1
            assert manifest.count("dir  repositories/platform") == 1
            assert "  managed-settings/claude.json" in manifest
            assert "  claude/settings.json" not in manifest
            assert "  claude/CLAUDE.md" not in manifest
            assert "  claude/hooks/" not in manifest
        else:
            assert claude_call not in setup
            assert claude_patch_call not in setup
            assert platform_call not in setup
            assert not (config / "managed-settings" / "claude.json").exists()
            assert not (config / "repositories" / "platform").exists()
            assert "managed-settings/claude.json" not in manifest
            assert "dir  claude" not in manifest
            assert "dir  repositories/platform" not in manifest

    assert "claude" != "pi-agent"
    for env_name in ENVIRONMENTS:
        setup = (built_root / env_name / "setup.sh").read_text()
        assert 'install_config_dir "$DIR/config/pi-angelini" "$HOME/repos/pi-angelini" "' not in setup


def test_generated_bundle_migrates_legacy_claude_settings_ownership(tmp_path: Path, built_root: Path) -> None:
    root = tmp_path.resolve()
    bundle = built_root / "macos"
    home = root / "home"
    state = root / "state"
    live = home / ".claude"
    live.mkdir(parents=True)
    settings = live / "settings.json"
    settings.write_text('{"includeCoAuthoredBy":true,"theme":"dark","permissions":{"allow":["local"]},"unmanaged":"keep"}\n')
    (live / "CLAUDE.md").write_text("legacy\n")
    manifest = state / "dotgen" / "install-config-dir" / "claude.manifest"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b"\0".join((b"dotgen-install-config-dir-v1", os.fsencode(str(live)), b"settings.json", b"CLAUDE.md")) + b"\0")
    script = root / "deploy-claude.sh"
    script.write_text(
        f"""set -euo pipefail
source {shlex.quote(str(bundle / "os_shim.sh"))}
export HOME={shlex.quote(str(home))}
export XDG_STATE_HOME={shlex.quote(str(state))}
install_config_dir {shlex.quote(str(bundle / "config" / "claude"))} "$HOME/.claude" claude settings.json
install_json_patch {shlex.quote(str(bundle / "config" / "managed-settings" / "claude.json"))} "$HOME/.claude/settings.json" 0600
"""
    )

    first = subprocess.run(["/bin/bash", str(script)], capture_output=True, text=True)

    assert first.returncode == 0, first.stderr
    merged = json.loads(settings.read_text())
    assert merged["includeCoAuthoredBy"] is False
    assert merged["theme"] == "light"
    assert merged["tui"] == "fullscreen"
    assert merged["skipAutoPermissionPrompt"] is True
    assert merged["skipWorkflowUsageWarning"] is True
    assert merged["permissions"] == {"allow": ["local"], "defaultMode": "auto"}
    assert merged["unmanaged"] == "keep"
    assert settings.stat().st_mode & 0o777 == 0o600
    records = manifest.read_bytes().split(b"\0")[:-1]
    assert b"settings.json" not in records[2:]
    assert b"CLAUDE.md" in records[2:]
    settings_inode = settings.stat().st_ino
    settings_bytes = settings.read_bytes()
    manifest_bytes = manifest.read_bytes()

    second = subprocess.run(["/bin/bash", str(script)], capture_output=True, text=True)

    assert second.returncode == 0, second.stderr
    assert settings.read_bytes() == settings_bytes
    assert settings.stat().st_ino == settings_inode
    assert manifest.read_bytes() == manifest_bytes


def test_generated_bundle_migrates_legacy_pi_settings_ownership(tmp_path: Path, built_root: Path) -> None:
    root = tmp_path.resolve()
    bundle = built_root / "macos"
    home = root / "home"
    state = root / "state"
    live = home / ".pi" / "agent"
    live.mkdir(parents=True)
    settings = live / "settings.json"
    settings.write_text('{"defaultModel":"legacy","lastChangelogVersion":"0.82.1","packages":["local"],"unmanaged":"keep"}\n')
    (live / "AGENTS.md").write_text("legacy\n")
    legacy_supacode = (
        live / "extensions/supacode/index.ts",
        live / "skills/supacode-cli/SKILL.md",
    )
    for path in legacy_supacode:
        path.parent.mkdir(parents=True)
        path.write_text("legacy managed Supacode\n")
    manifest = state / "dotgen" / "install-config-dir" / "pi-agent.manifest"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(
        b"\0".join(
            (
                b"dotgen-install-config-dir-v1",
                os.fsencode(str(live)),
                b"settings.json",
                b"AGENTS.md",
                b"extensions/supacode/index.ts",
                b"skills/supacode-cli/SKILL.md",
            )
        )
        + b"\0"
    )
    script = root / "deploy-pi.sh"
    script.write_text(
        f"""set -euo pipefail
source {shlex.quote(str(bundle / "os_shim.sh"))}
export HOME={shlex.quote(str(home))}
export XDG_STATE_HOME={shlex.quote(str(state))}
install_config_dir {shlex.quote(str(bundle / "config" / "pi" / "agent"))} "$HOME/.pi/agent" pi-agent settings.json
install_json_patch {shlex.quote(str(bundle / "config" / "managed-settings" / "pi.json"))} "$HOME/.pi/agent/settings.json" 0600
"""
    )

    first = subprocess.run(["/bin/bash", str(script)], capture_output=True, text=True)

    assert first.returncode == 0, first.stderr
    merged = json.loads(settings.read_text())
    assert merged["defaultModel"] == "gpt-5.6-sol"
    assert merged["defaultThinkingLevel"] == "high"
    assert merged["packages"][-1] == "~/repos/pi-angelini"
    assert merged["theme"] == "light"
    assert merged["lastChangelogVersion"] == "0.82.1"
    assert merged["unmanaged"] == "keep"
    assert settings.stat().st_mode & 0o777 == 0o600
    records = manifest.read_bytes().split(b"\0")[:-1]
    assert b"settings.json" not in records[2:]
    assert b"AGENTS.md" in records[2:]
    assert not any(path.exists() for path in legacy_supacode)
    assert b"extensions/supacode/index.ts" not in records[2:]
    assert b"skills/supacode-cli/SKILL.md" not in records[2:]
    settings_inode = settings.stat().st_ino
    settings_bytes = settings.read_bytes()
    manifest_bytes = manifest.read_bytes()

    second = subprocess.run(["/bin/bash", str(script)], capture_output=True, text=True)

    assert second.returncode == 0, second.stderr
    assert settings.read_bytes() == settings_bytes
    assert settings.stat().st_ino == settings_inode
    assert manifest.read_bytes() == manifest_bytes


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
