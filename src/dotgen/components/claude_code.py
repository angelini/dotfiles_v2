from dataclasses import dataclass

from dotgen.components.agent_config import _agent_config_root, managed_settings  # pyright: ignore[reportPrivateUsage]
from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.vendor import VendorDir

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
install_config_dir "$DIR/config/claude" "$HOME/.claude" "claude" "settings.json"
install_json_patch "$DIR/config/managed-settings/claude.json" "$HOME/.claude/settings.json" 0600
_install_serena
_register_serena_mcp
"""


@dataclass(frozen=True)
class ClaudeCode:
    name: str = "claude_code"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP,
            configs=(ConfigFile(dest="managed-settings/claude.json", content=managed_settings("claude"), mode=0o600),),
            vendors=(
                VendorDir(
                    source=_agent_config_root() / "claude",
                    dest="claude",
                    include_globs=("CLAUDE.md", "agents/*.md", "commands/review.md", "hooks/*", "skills/**"),
                ),
            ),
        )
