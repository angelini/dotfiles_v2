import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from dotgen.components.codex import Codex
from dotgen.registry import ENVIRONMENTS

SCRIPT = Path(__file__).parents[1] / "src/dotgen/resources/merge_codex_settings.py"


def test_codex_settings_merge_preserves_state_and_comments(tmp_path: Path) -> None:
    fragment = Codex().render(ENVIRONMENTS["macos"])
    patch = tmp_path / "patch.json"
    patch.write_text(next(c.content for c in fragment.configs if c.dest == "managed-settings/codex.json"))
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
            "sandbox_workspace_write": {"network_access": True, "writable_roots": ["/example/cache"]},
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
