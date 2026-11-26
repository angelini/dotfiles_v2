import json
import os
import subprocess
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from dotgen.components.codex import Codex
from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_env

SCRIPT = Path(__file__).parents[1] / "src/dotgen/resources/merge_codex_settings.py"


@pytest.mark.parametrize("env_name", ["macos", "debian", "cachyos"])
def test_codex_bundle_installs_and_updates_skills(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env_name: str) -> None:
    root = tmp_path.resolve()
    source = root / "agent-config"
    settings = source / "settings" / "codex.managed.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}\n")
    skill = source / "codex" / "skills" / "work-recap"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("shared recap\n")
    helper = skill / "scripts" / "recap.sh"
    helper.parent.mkdir()
    helper.write_text("#!/bin/bash\nexit 0\n")
    helper.chmod(0o755)
    excluded_skill = source / "codex" / "skills" / "supacode-cli"
    excluded_skill.mkdir()
    (excluded_skill / "SKILL.md").write_text("must not deploy\n")
    (source / "codex" / "auth.json").write_text("must not deploy\n")
    monkeypatch.setenv("DOTGEN_AGENT_CONFIG_ROOT", str(source))
    env = replace(ENVIRONMENTS[env_name], components=(Codex(),))
    bundle = root / "bundle"
    build_env(env, bundle)
    assert not (bundle / "config" / "codex" / "auth.json").exists()
    assert not (bundle / "config" / "codex" / "skills" / "supacode-cli").exists()

    home = root / "home"
    live = home / ".agents" / "skills"
    local_skill = live / "local" / "SKILL.md"
    local_skill.parent.mkdir(parents=True)
    local_skill.write_text("keep local skill\n")
    install = next(line for line in Codex().render(env).setup.splitlines() if line.startswith("install_config_dir "))
    command = 'set -euo pipefail\nsource "$DIR/os_shim.sh"\n' + install
    process_env = {**os.environ, "HOME": str(home), "DIR": str(bundle), "XDG_STATE_HOME": str(root / "state")}
    for _ in range(2):
        subprocess.run(["bash", "-c", command], env=process_env, check=True, capture_output=True, text=True)
        assert (live / "work-recap" / "SKILL.md").read_text() == "shared recap\n"
        assert (live / "work-recap" / "scripts" / "recap.sh").stat().st_mode & 0o111
        assert local_skill.read_text() == "keep local skill\n"
        assert not (live / "supacode-cli").exists()
    (skill / "SKILL.md").write_text("updated recap\n")
    helper.unlink()
    build_env(env, bundle)
    subprocess.run(["bash", "-c", command], env=process_env, check=True, capture_output=True, text=True)
    assert (live / "work-recap" / "SKILL.md").read_text() == "updated recap\n"
    assert not (live / "work-recap" / "scripts" / "recap.sh").exists()
    assert local_skill.read_text() == "keep local skill\n"


def test_codex_settings_merge_preserves_state_and_comments(tmp_path: Path) -> None:
    fragment = Codex().render(ENVIRONMENTS["macos"])
    patch = tmp_path / "patch.json"
    patch.write_text(next(c.content for c in fragment.configs if c.dest == "managed-settings/codex.json"))
    managed = json.loads(patch.read_text())
    destination = tmp_path / "config.toml"
    destination.write_text(
        '# My model\nmodel = "custom"\nsandbox_mode = "danger-full-access"\n'
        '[sandbox_workspace_write]\nnetwork_access = false\nwritable_roots = ["/example/cache"]\n'
        '[mcp_servers.local]\ncommand = "local-server"\n'
    )
    for _ in range(2):
        subprocess.run([sys.executable, str(SCRIPT), str(patch), str(destination)], check=True)
        content = destination.read_text()
        assert "# My model" in content
        assert tomllib.loads(content) == {
            "model": "custom",
            "sandbox_mode": "workspace-write",
            "approval_policy": "on-request",
            "sandbox_workspace_write": {
                "network_access": managed["sandbox_workspace_write"]["network_access"],
                "writable_roots": managed["sandbox_workspace_write"]["writable_roots"],
            },
            "mcp_servers": {"local": {"command": "local-server"}},
        }
        assert destination.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("existing", [None, "invalid = [", "model = 1\nmodel = 2\n"])
def test_codex_settings_creation_and_invalid_toml(tmp_path: Path, existing: str | None) -> None:
    patch = tmp_path / "patch.json"
    patch.write_text(json.dumps({"approval_policy": "never"}))
    destination = tmp_path / "nested/config.toml"
    if existing is not None:
        destination.parent.mkdir()
        destination.write_text(existing)
    result = subprocess.run([sys.executable, str(SCRIPT), str(patch), str(destination)], capture_output=True)
    if existing is None:
        assert result.returncode == 0, result.stderr
        assert tomllib.loads(destination.read_text()) == {"approval_policy": "never"}
    else:
        assert result.returncode != 0
        assert destination.read_text() == existing


def test_codex_settings_reject_symlink(tmp_path: Path) -> None:
    patch = tmp_path / "patch.json"
    patch.write_text("{}")
    real = tmp_path / "real.toml"
    real.write_text('model = "original"\n')
    link = tmp_path / "config.toml"
    link.symlink_to(real)
    result = subprocess.run([sys.executable, str(SCRIPT), str(patch), str(link)], capture_output=True)
    assert result.returncode != 0
    assert real.read_text() == 'model = "original"\n'
