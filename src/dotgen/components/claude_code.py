import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotgen.fragment import ConfigFile, Fragment

if TYPE_CHECKING:
    from dotgen.environment import Environment

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

_CLAUDE_MD = """\
# CLAUDE.md

Rules for generating responses:

- Always keep output consice
- If possible include code examples
- Include references and links to docs to support the code examples
- Reference APIs based on local installed version, read docs online for those specific versions
- Do not guess what APIs exist, be clear if you cannot generate code with known APIs

## Code search

- For symbol-level work (definitions, callers, rename) prefer Serena's `find_symbol`, `find_referencing_symbols`, and `get_symbols_overview` over grep.
- Use grep/ripgrep for raw string matches: configs, comments, log lines, literal values.
- At the start of a coding task in a Serena-enabled repo, call `initial_instructions` once.

## Comments

- Default to no comment. Names and types should carry the meaning.
- Do not restate what the code does, and do not record implementation-session context ("this was added to address X", "fixes the bug from earlier"). That belongs in the commit or PR.
- Write a comment only when it explains something a reader cannot recover from the code: a non-obvious invariant, a hidden constraint, a workaround for a specific external bug, or surprising behavior.
"""

_SERENA_HOOK = r"""#!/usr/bin/env bash
set -u

if jq -e --arg cwd "$PWD" '.projects[$cwd].mcpServers.serena // empty' \
     "$HOME/.claude.json" >/dev/null 2>&1 \
   || { [ -f .mcp.json ] && jq -e '.mcpServers.serena // empty' .mcp.json >/dev/null 2>&1; }; then
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: (
        "Serena MCP is available in this project. Before any code search or coding task, "
        + "call `mcp__serena__initial_instructions` once to load the Serena manual. "
        + "For symbol-level work (finding definitions, callers, renaming, file symbol overviews), "
        + "prefer Serena tools (`find_symbol`, `find_referencing_symbols`, `get_symbols_overview`) "
        + "over grep/ripgrep. Use grep only for raw string matches: configs, comments, log lines, "
        + "literal values."
      )
    }
  }'
fi
"""

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
  "$uv_bin" tool install --from git+https://github.com/oraios/serena serena-agent
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
install_config "$DIR/config/claude/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
install_config "$DIR/config/claude/hooks/serena-reminder.sh" "$HOME/.claude/hooks/serena-reminder.sh"
if [ "$DOTGEN_MODE" = deploy ]; then
  chmod +x "$HOME/.claude/hooks/serena-reminder.sh"
  _install_serena
  _register_serena_mcp
fi
"""

_BASHRC = """\
if bin_exists claude; then
  source <(claude completion bash 2>/dev/null) 2>/dev/null || true
fi
"""


@dataclass(frozen=True)
class ClaudeCode:
    name: str = "claude_code"

    def applies_to(self, env: "Environment") -> bool:
        return True

    def render(self, env: "Environment") -> Fragment:
        return Fragment(
            setup=_SETUP,
            bashrc=_BASHRC,
            configs=(
                ConfigFile(dest="claude/settings.json", content=_SETTINGS_JSON),
                ConfigFile(dest="claude/CLAUDE.md", content=_CLAUDE_MD),
                ConfigFile(
                    dest="claude/hooks/serena-reminder.sh",
                    content=_SERENA_HOOK,
                    mode=0o755,
                ),
            ),
        )
