import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS

_SETTINGS_JSON = (
    json.dumps(
        {
            "defaultProvider": "openai-codex",
            "defaultModel": "gpt-5.5",
            "defaultThinkingLevel": "high",
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
                "npm:@plannotator/pi-extension",
                "npm:@dreki-gg/pi-context7",
                "npm:@juicesharp/rpiv-ask-user-question",
                "npm:@juicesharp/rpiv-todo",
                "npm:@samfp/pi-memory",
                "~/repos/pi-angelini",
            ],
            "quietStartup": False,
            "collapseChangelog": True,
            "theme": "light",
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
                    "apiKey": "GEMINI_API_KEY",
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

_RESOURCE_ROOT = Path(__file__).resolve().parents[1] / "resources" / "pi_agent"


def _resource_text(relative_path: str) -> str:
    return (_RESOURCE_ROOT / relative_path).read_text()


_PLANNOTATOR_JSON = _resource_text("plannotator.json")
_SUPACODE_EXTENSION_TS = _resource_text("extensions/supacode/index.ts.txt")
_SUPACODE_SKILL_MD = _resource_text("skills/supacode-cli/SKILL.md")

_PI_ANGELINI_EXCLUDED_DIRS = frozenset(
    {".git", "node_modules", ".pytest_cache", ".ruff_cache", ".serena", "dist"}
)
_PI_ANGELINI_EXCLUDED_NAMES = frozenset({"package-lock.json", "pi-system-audit-plan.md"})


def _pi_angelini_root() -> Path:
    configured = os.environ.get("DOTGEN_PI_ANGELINI_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4] / "pi-angelini"


def _pi_angelini_configs() -> tuple[ConfigFile, ...]:
    root = _pi_angelini_root()
    if not root.is_dir():
        raise FileNotFoundError(f"pi-angelini source not found: {root}")

    configs: list[ConfigFile] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in _PI_ANGELINI_EXCLUDED_DIRS for part in rel.parts):
            continue
        if path.is_dir():
            continue
        if path.name in _PI_ANGELINI_EXCLUDED_NAMES or path.name.endswith(".test.ts"):
            continue
        configs.append(
            ConfigFile(dest=f"pi-angelini/{rel.as_posix()}", content=path.read_text())
        )
    return tuple(configs)

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
    "@plannotator/pi-extension",
    "@dreki-gg/pi-context7",
    "@juicesharp/rpiv-ask-user-question",
    "@juicesharp/rpiv-todo",
    "@samfp/pi-memory",
)

_PI_SANDBOX_SH = r"""#!/usr/bin/env bash
set -euo pipefail

_die() {
  printf 'pi-sandbox: %s\n' "$*" >&2
  exit 2
}

_load_dotgen_secrets() {
  local f="${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/secrets.env"
  [ -r "$f" ] || return 0
  set -a
  # shellcheck disable=SC1090
  source "$f"
  set +a
}

_resolve_path() {
  cd "$1" 2>/dev/null && pwd -P
}

main() {
  local repos="$HOME/repos"
  local cwd real_repos pi_bin
  cwd="$(_resolve_path "$PWD")" || _die "cannot resolve current directory: $PWD"
  real_repos="$(_resolve_path "$repos")" || _die "missing repos directory: $repos"
  case "$cwd" in
    "$real_repos"|"$real_repos"/*) ;;
    *) _die "run pi-sandbox from within $repos" ;;
  esac

  pi_bin="$(command -v pi)" || _die "pi binary not found"
  [ -x "$pi_bin" ] || _die "pi binary is not executable: $pi_bin"

  _load_dotgen_secrets

  case "$(uname -s)" in
    Darwin) _run_macos "$pi_bin" "$@" ;;
    Linux) _run_linux "$pi_bin" "$@" ;;
    *) _die "unsupported OS: $(uname -s)" ;;
  esac
}

_run_macos() {
  local pi_bin="$1" profile="$HOME/.config/pi/sandbox/pi-macos.sb"
  shift
  [ -r "$profile" ] || _die "missing sandbox profile: $profile"
  exec env -i \
    "HOME=$HOME" \
    "PATH=${PATH:-/usr/bin:/bin}" \
    "SHELL=${SHELL:-/bin/bash}" \
    "TERM=${TERM:-xterm-256color}" \
    "LANG=${LANG:-C.UTF-8}" \
    "GEMINI_API_KEY=${GEMINI_API_KEY:-}" \
    "EXA_API_KEY=${EXA_API_KEY:-}" \
    "CONTEXT7_API_KEY=${CONTEXT7_API_KEY:-}" \
    sandbox-exec \
    -D "HOME=$HOME" \
    -D "REPOS=$HOME/repos" \
    -D "PI_AGENT=$HOME/.pi/agent" \
    -D "TMPDIR=${TMPDIR:-/tmp}" \
    -f "$profile" \
    "$pi_bin" "$@"
}

_run_linux() {
  local pi_bin="$1"
  shift
  command -v bwrap >/dev/null 2>&1 || _die "bwrap is required"
  exec env -i \
    "HOME=$HOME" \
    "PATH=${PATH:-/usr/bin:/bin}" \
    "SHELL=${SHELL:-/bin/bash}" \
    "TERM=${TERM:-xterm-256color}" \
    "LANG=${LANG:-C.UTF-8}" \
    "GEMINI_API_KEY=${GEMINI_API_KEY:-}" \
    "EXA_API_KEY=${EXA_API_KEY:-}" \
    "CONTEXT7_API_KEY=${CONTEXT7_API_KEY:-}" \
    bwrap \
    --unshare-user-try \
    --unshare-ipc \
    --unshare-pid \
    --die-with-parent \
    --proc /proc \
    --dev-bind /dev /dev \
    --tmpfs /tmp \
    --dir "$HOME" \
    --dir "$HOME/.pi" \
    --dir "$HOME/.local" \
    --dir "$HOME/.local/share" \
    --dir "$HOME/.local/state" \
    --bind "$HOME/repos" "$HOME/repos" \
    --bind "$HOME/.pi/agent" "$HOME/.pi/agent" \
    --ro-bind-try "$HOME/.local/share/fnm" "$HOME/.local/share/fnm" \
    --ro-bind-try "$HOME/.local/state/fnm_multishells" "$HOME/.local/state/fnm_multishells" \
    --ro-bind /usr /usr \
    --ro-bind /bin /bin \
    --ro-bind-try /lib /lib \
    --ro-bind-try /lib64 /lib64 \
    --ro-bind /etc /etc \
    --setenv HOME "$HOME" \
    --chdir "$PWD" \
    "$pi_bin" "$@"
}

main "$@"
"""

_PI_MACOS_SB = r"""(version 1)
(deny default)

(allow process*)
(allow signal)
(allow sysctl*)
(allow mach-lookup)

(allow file-read* file-write* (subpath (param "REPOS")))
(allow file-read* file-write* (subpath (param "PI_AGENT")))
(allow file-read* file-write* (subpath (param "TMPDIR")))
(allow file-read* file-write-data
  (literal "/dev/null")
  (literal "/dev/zero"))

(allow file-read*
  (subpath "/bin")
  (subpath "/sbin")
  (subpath "/usr/bin")
  (subpath "/usr/sbin")
  (subpath "/usr/lib")
  (subpath "/usr/share")
  (subpath "/System/Library")
  (subpath "/Library")
  (subpath "/opt/homebrew")
  (subpath "/usr/local")
  (subpath (string-append (param "HOME") "/.local/share/fnm"))
  (subpath (string-append (param "HOME") "/.local/state/fnm_multishells")))

(allow file-read-metadata
  (literal "/")
  (literal (param "HOME"))
  (literal (string-append (param "HOME") "/.pi"))
  (literal (string-append (param "HOME") "/.local"))
  (literal (string-append (param "HOME") "/.local/share"))
  (literal (string-append (param "HOME") "/.local/state"))
  (literal "/private")
  (literal "/private/tmp")
  (literal "/private/var")
  (literal "/private/var/tmp"))

(deny file* (with no-report)
  (subpath (string-append (param "HOME") "/.ssh"))
  (subpath (string-append (param "HOME") "/.gnupg"))
  (subpath (string-append (param "HOME") "/.aws"))
  (subpath (string-append (param "HOME") "/.azure"))
  (subpath (string-append (param "HOME") "/.config/gcloud"))
  (subpath (string-append (param "HOME") "/.config/dotgen"))
  (subpath (string-append (param "HOME") "/.kube"))
  (literal (string-append (param "HOME") "/.docker/config.json"))
  (literal (string-append (param "HOME") "/.config/gh/hosts.yml"))
  (literal (string-append (param "HOME") "/.git-credentials"))
  (literal (string-append (param "HOME") "/.netrc"))
  (literal (string-append (param "HOME") "/.npmrc"))
  (literal (string-append (param "HOME") "/.pypirc"))
  (literal (string-append (param "HOME") "/.cargo/credentials.toml"))
  (subpath (string-append (param "HOME") "/.claude"))
  (literal (string-append (param "HOME") "/.bash_history"))
  (literal (string-append (param "HOME") "/.zsh_history"))
  (literal (string-append (param "HOME") "/.python_history")))
"""

_ALIAS = """\
pi() {
  pi-sandbox "$@"
}

pi-unsafe() {
  command pi "$@"
}
"""

_SETUP_BASE = (
    "\n".join(f"install_npm_global {pkg}" for pkg in _PI_PACKAGES)
    + r"""
ensure_dir "$HOME/.pi/agent"
ensure_dir "$HOME/.config/pi/sandbox"
ensure_dir "$HOME/.local/bin"
install_config "$DIR/config/pi/agent/settings.json" "$HOME/.pi/agent/settings.json"
install_config "$DIR/config/pi/agent/models.json" "$HOME/.pi/agent/models.json"
install_config "$DIR/config/pi/agent/web-search.json" "$HOME/.pi/agent/web-search.json"
install_config "$DIR/config/pi/agent/AGENTS.md" "$HOME/.pi/agent/AGENTS.md"
install_config "$DIR/config/pi/agent/plannotator.json" "$HOME/.pi/agent/plannotator.json"
install_config "$DIR/config/pi/agent/extensions/supacode/index.ts" "$HOME/.pi/agent/extensions/supacode/index.ts"
install_config "$DIR/config/pi/agent/skills/supacode-cli/SKILL.md" "$HOME/.pi/agent/skills/supacode-cli/SKILL.md"
install_config "$DIR/config/pi/sandbox/pi-macos.sb" "$HOME/.config/pi/sandbox/pi-macos.sb"
install -m 0755 "$DIR/config/pi/sandbox/pi-sandbox.sh" "$HOME/.local/bin/pi-sandbox"

_install_pi_angelini() {
  local src="$DIR/config/pi-angelini" dst="$HOME/repos/pi-angelini"
  if [ "$DOTGEN_MODE" = diff ]; then
    if [ ! -d "$dst" ]; then
      printf '+ COPY   %s\n' "$dst"
    elif ! diff -qr -x .git -x node_modules -x .pytest_cache "$src" "$dst" >/dev/null 2>&1; then
      printf '~ SYNC   %s\n' "$dst"
    fi
    return 0
  fi

  ensure_dir "$HOME/repos"
  if [ -d "$dst/.git" ]; then
    cp -R "$src"/. "$dst"/
    return 0
  fi

  rm -rf "$dst"
  ensure_dir "$dst"
  cp -R "$src"/. "$dst"/
}
_install_pi_angelini
"""
)


def _setup_for(env: Environment) -> str:
    parts: list[str] = []
    if env.os is OS.DEBIAN:
        parts.append("install_package bubblewrap")
    parts.append(_SETUP_BASE)
    return "\n".join(parts)


@dataclass(frozen=True)
class PiAgent:
    name: str = "pi_agent"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_setup_for(env),
            alias=_ALIAS,
            configs=(
                ConfigFile(dest="pi/agent/settings.json", content=_SETTINGS_JSON),
                ConfigFile(dest="pi/agent/models.json", content=_MODELS_JSON, mode=0o600),
                ConfigFile(dest="pi/agent/web-search.json", content=_WEB_SEARCH_JSON),
                ConfigFile(dest="pi/agent/AGENTS.md", content=_AGENTS_MD),
                ConfigFile(dest="pi/agent/plannotator.json", content=_PLANNOTATOR_JSON),
                ConfigFile(dest="pi/agent/extensions/supacode/index.ts", content=_SUPACODE_EXTENSION_TS),
                ConfigFile(dest="pi/agent/skills/supacode-cli/SKILL.md", content=_SUPACODE_SKILL_MD),
                ConfigFile(dest="pi/sandbox/pi-sandbox.sh", content=_PI_SANDBOX_SH, mode=0o755),
                ConfigFile(dest="pi/sandbox/pi-macos.sb", content=_PI_MACOS_SB),
            )
            + _pi_angelini_configs(),
            secrets=frozenset({"CONTEXT7_API_KEY", "EXA_API_KEY", "GEMINI_API_KEY"}),
        )
