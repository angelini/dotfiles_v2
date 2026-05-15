import json
from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment

_SETTINGS_JSON = (
    json.dumps(
        {
            "defaultProvider": "openai-codex",
            "defaultModel": "gpt-5.5",
            "defaultThinkingLevel": "medium",
            "enabledModels": [
                "google/gemini-3-flash-preview",
                "openai-codex/gpt-5.5",
            ],
            "packages": [
                "npm:pi-lens",
                "npm:pi-mcp-adapter",
                "npm:pi-subagents",
                "npm:pi-web-access",
                "npm:pi-simplify",
                "npm:@juicesharp/rpiv-ask-user-question",
                "npm:@juicesharp/rpiv-todo",
                "npm:@samfp/pi-memory",
            ],
            "quietStartup": False,
            "collapseChangelog": True,
            "theme": "light",
            "lastChangelogVersion": "0.74.0",
        },
        indent=2,
    )
    + "\n"
)

_MODELS_JSON = (
    json.dumps(
        {
            "providers": {
                "google": {
                    "baseUrl": "https://generativelanguage.googleapis.com/v1beta",
                    "api": "google-generative-ai",
                    "apiKey": "${GOOGLE_GENERATIVE_AI_API_KEY}",
                    "models": [
                        {
                            "id": "gemini-3-flash-preview",
                            "name": "Gemini 3 Flash",
                            "input": ["text", "image"],
                            "contextWindow": 1048576,
                            "maxTokens": 65536,
                            "reasoning": True,
                        }
                    ],
                }
            }
        },
        indent=2,
    )
    + "\n"
)

_WEB_SEARCH_JSON = json.dumps({"provider": "exa"}, indent=2) + "\n"

_AGENTS_MD = """\
# Agent instructions for this workspace

Use these instructions for every pi session from this workspace or any subdirectory.

## Core behavior

- Keep responses concise.
- Prefer minimal, targeted changes over broad rewrites.
- Present reasoning summaries in a concise, matter-of-fact tone. Avoid first-person phrasing, speculation, enthusiasm, or motivational language. Use short declarative sentences.
- When suggesting code changes, show a diff or minimal snippet.
- Do not record implementation-session context in code comments.
- Do not guess APIs. If an API matters, verify the installed version first, then check docs for that version.
- At task start, if `.pi/APPEND_SYSTEM.md` exists in the repo, read it before running commands.

## Tooling

- Use `read` for files, not `cat`/`sed`.
- Use `bash` for filesystem discovery and project commands.
- Use `edit` for precise file changes.
- Use `todo` for work with 3+ meaningful steps.
- Use `ask_user_question` when progress depends on a user-owned decision.
- Use `web_search`, `code_search`, or `fetch_content` for current docs or external APIs.
- Use subagents for reviewing, researching, planning and scouting code bases.

## Languages and validation

- Be ready to work in Rust, Python, TypeScript, and Go.
- Prefer LSP/linter/type-checker feedback before declaring changes complete.
- If diagnostics affect files you touched, fix them or explicitly explain why not.
- Do not invent build/test commands. Read `package.json`, `Cargo.toml`, `pyproject.toml`, or `go.mod` first.

## Project command conventions

- In Nx monorepos, prefer `npx nx <target> <project>` over direct `npm run`.
- Use the repository’s local instructions before proposing commands.

## Final checks

- After non-trivial diffs, run `/simplify --staged` and apply suggestions you agree with.
"""

_PI_PACKAGES = (
    "@earendil-works/pi-coding-agent",
    "pi-lens",
    "pi-mcp-adapter",
    "pi-subagents",
    "pi-web-access",
    "pi-simplify",
    "@juicesharp/rpiv-ask-user-question",
    "@juicesharp/rpiv-todo",
    "@samfp/pi-memory",
)

_SETUP = (
    "\n".join(f"install_npm_global {pkg}" for pkg in _PI_PACKAGES)
    + """
ensure_dir "$HOME/.pi/agent"
install_config "$DIR/config/pi/agent/settings.json" "$HOME/.pi/agent/settings.json"
install_config_template "$DIR/config/pi/agent/models.json" "$HOME/.pi/agent/models.json" "GOOGLE_GENERATIVE_AI_API_KEY"
install_config "$DIR/config/pi/agent/web-search.json" "$HOME/.pi/agent/web-search.json"
install_config "$DIR/config/pi/agent/AGENTS.md" "$HOME/.pi/agent/AGENTS.md"
"""
)


@dataclass(frozen=True)
class PiAgent:
    name: str = "pi_agent"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP,
            configs=(
                ConfigFile(dest="pi/agent/settings.json", content=_SETTINGS_JSON),
                ConfigFile(dest="pi/agent/models.json", content=_MODELS_JSON, mode=0o600),
                ConfigFile(dest="pi/agent/web-search.json", content=_WEB_SEARCH_JSON),
                ConfigFile(dest="pi/agent/AGENTS.md", content=_AGENTS_MD),
            ),
            secrets=frozenset({"EXA_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"}),
        )
