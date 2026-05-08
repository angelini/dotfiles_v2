from pathlib import Path

from dotgen.environment import ENVIRONMENTS, Environment
from dotgen.fragment import Fragment
from dotgen.shim import OSShim

SETUP_HEADER = """\
#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOTGEN_MODE="${1-}"
case "$DOTGEN_MODE" in
  diff|deploy) ;;
  -h|--help|help)
    printf 'usage: %s {diff|deploy}\\n' "$0"
    printf '  diff   show pending changes (read-only)\\n'
    printf '  deploy apply changes (overwrites configs)\\n'
    exit 0 ;;
  "")
    printf 'usage: %s {diff|deploy}\\n' "$0" >&2; exit 2 ;;
  *)
    printf 'unknown mode: %s\\nusage: %s {diff|deploy}\\n' "$DOTGEN_MODE" "$0" >&2; exit 2 ;;
esac
export DOTGEN_MODE
source "$DIR/os_shim.sh"
[ "$DOTGEN_MODE" = deploy ] && update_pkg_index
"""

SETUP_FOOTER = (
    'if [ "$DOTGEN_MODE" = diff ]; then\n'
    '  log "diff complete (no changes applied)"\n'
    "else\n"
    '  log "setup complete"\n'
    "fi\n"
)

ALIAS_HEADER = "# alias.sh — sourced by ~/.bashrc\n"

BASHRC_HEADER = """\
# .bashrc
export PATH="$HOME/bin:$HOME/.local/bin:$PATH"
[ -f "$HOME/.aliases" ] && source "$HOME/.aliases"
"""


def build_env(env: Environment, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    shim_text = OSShim(env.os).render()
    (out_dir / "os_shim.sh").write_text(shim_text)

    fragment = _merge_fragments(env)

    setup = SETUP_HEADER
    if fragment.setup:
        setup += "\n" + fragment.setup
        if not setup.endswith("\n"):
            setup += "\n"
    setup += SETUP_FOOTER
    (out_dir / "setup.sh").write_text(setup)

    alias_text = ALIAS_HEADER + (fragment.alias + "\n" if fragment.alias else "")
    (out_dir / "alias.sh").write_text(alias_text)

    bashrc_text = BASHRC_HEADER + (fragment.bashrc + "\n" if fragment.bashrc else "")
    (out_dir / ".bashrc").write_text(bashrc_text)

    if fragment.configs:
        config_dir = out_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        for cf in fragment.configs:
            dest = config_dir / cf.dest
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(cf.content)
            dest.chmod(cf.mode)


def build_all(out_root: Path) -> None:
    for name, env in ENVIRONMENTS.items():
        build_env(env, out_root / name)


def _merge_fragments(env: Environment) -> Fragment:
    result = Fragment()
    for component in env.components:
        if component.applies_to(env):
            result = result.merge(component.render(env))
    return result
