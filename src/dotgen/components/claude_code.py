import json
from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment

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

- Always keep output concise
- When suggesting code changes, show the diff or a minimal snippet, not just a description
- Include references and links to docs to support the code examples
- Before citing an API, run npm ls <pkg> (or go list -m) to confirm the installed version, then fetch docs for that version
- Do not guess what APIs exist, be clear if you cannot generate code with known APIs

## Comments

- Default to zero comments. Code should explain itself through naming and structure.
- Only add a comment to explain *why*, never *what*. If a comment restates what the code does, delete it.
- A comment is justified only when it documents one of: a non-obvious workaround, a counterintuitive constraint,
  a deliberate edge-case decision, or a link to an issue/spec. If it's none of these, don't write it.
- Never narrate the change you just made or record implementation-session context.
- Never add section-divider comments, restate a function/variable name, or describe obvious control flow.

Bad (delete these):

```ts
// Loop over the users and update each one
for (const user of users) { ... }

// Set the flag to true
isReady = true;
```

Good (keep):

```ts
// Stripe rounds half-up; we floor here to match the invoice total (BILL-1423)
const cents = Math.floor(amount * 100);
```

## Code search

- For symbol-level work (definitions, callers, rename) prefer Serena's `find_symbol`, `find_referencing_symbols`, and `get_symbols_overview` over grep
- Use grep/ripgrep for raw string matches: configs, comments, log lines, literal values
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
install_config "$DIR/config/claude/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
install_config "$DIR/config/claude/hooks/serena-reminder.sh" "$HOME/.claude/hooks/serena-reminder.sh"
if [ "$DOTGEN_MODE" = deploy ]; then
  chmod +x "$HOME/.claude/hooks/serena-reminder.sh"
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
