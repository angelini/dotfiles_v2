from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment


@dataclass(frozen=True)
class Codex:
    name: str = "codex"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup="install_npm_global @openai/codex\n"
            'codex mcp add serena -- "$HOME/.local/bin/serena" start-mcp-server --context codex --project-from-cwd\n'
        )
