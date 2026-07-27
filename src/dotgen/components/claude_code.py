import json
from dataclasses import dataclass

from dotgen.components.agent_config import _agent_config_root  # pyright: ignore[reportPrivateUsage]
from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.vendor import VendorDir

_SETTINGS_JSON = (
    json.dumps(
        {
            "includeCoAuthoredBy": False,
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "~/.claude/hooks/serena-reminder.sh",
                            }
                        ]
                    }
                ]
            },
        },
        indent=2,
    )
    + "\n"
)

_SETUP = r"""export PATH="$HOME/.local/bin:$PATH"
install_script claude https://claude.ai/install.sh
_install_serena() {
  local uv_bin
  uv_bin="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"
  if [ ! -x "$uv_bin" ]; then
    error "_install_serena: uv not found"
    return 1
  fi
  if "$uv_bin" tool list 2>/dev/null | grep -q '^serena-agent'; then
    return 0
  fi
  "$uv_bin" tool install --from https://github.com/oraios/serena/archive/refs/heads/main.tar.gz serena-agent
}
_register_serena_mcp() {
  if ! bin_exists claude; then
    return 0
  fi
  if claude mcp list 2>/dev/null | grep -q '^serena'; then
    return 0
  fi
  claude mcp add serena -s user -- serena start-mcp-server --context claude-code || true
}
install_config "$DIR/config/claude/settings.json" "$HOME/.claude/settings.json"
install_config_dir "$DIR/config/claude" "$HOME/.claude" "claude"
if [ "$DOTGEN_MODE" = deploy ]; then
  _install_serena
  _register_serena_mcp
fi
"""


@dataclass(frozen=True)
class ClaudeCode:
    name: str = "claude_code"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP,
            configs=(ConfigFile(dest="claude/settings.json", content=_SETTINGS_JSON),),
            vendors=(
                VendorDir(
                    source=_agent_config_root() / "claude",
                    dest="claude",
                    include_globs=("CLAUDE.md", "agents/*.md", "commands/review.md", "hooks/*", "skills/**"),
                ),
            ),
        )
