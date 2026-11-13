from dataclasses import dataclass
from pathlib import Path

from dotgen.components.agent_config import _agent_config_root, managed_settings  # pyright: ignore[reportPrivateUsage]
from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.vendor import VendorDir


@dataclass(frozen=True)
class Codex:
    name: str = "codex"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup="install_npm_global @openai/codex\n"
            'install_config_dir "$DIR/config/codex/skills" "$HOME/.agents/skills" "codex-skills"\n'
            'uv run --no-project --python 3.12 --with tomlkit==0.13.3 python "$DIR/config/codex/merge-settings.py" '
            '"$DIR/config/managed-settings/codex.json" "${CODEX_HOME:-$HOME/.codex}/config.toml"\n'
            'codex mcp add serena -- "$HOME/.local/bin/serena" start-mcp-server --context codex --project-from-cwd\n',
            configs=(
                ConfigFile(dest="managed-settings/codex.json", content=managed_settings("codex"), mode=0o600),
                ConfigFile(dest="codex/merge-settings.py", content=(Path(__file__).parents[1] / "resources" / "merge_codex_settings.py").read_text()),
            ),
            vendors=(
                VendorDir(
                    source=_agent_config_root() / "codex" / "skills",
                    dest="codex/skills",
                    exclude_dirs=frozenset({"supacode-cli"}),
                ),
            ),
        )
