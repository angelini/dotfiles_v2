import textwrap
from pathlib import Path

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.registry import ENVIRONMENTS
from dotgen.secrets import DESCRIPTIONS
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
if [ "$DOTGEN_MODE" = deploy ]; then
  bin_exists envsubst || install_package gettext
  if [ ! -r "${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/secrets.env" ]; then
    error "deploy requires ${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/secrets.env"
    error "copy from: $DIR/config/dotgen/secrets.env.template"
    exit 2
  fi
fi
[ "$DOTGEN_MODE" = deploy ] && update_pkg_index
"""

SETUP_FOOTER = 'if [ "$DOTGEN_MODE" = deploy ]; then\n  log "setup complete"\nfi\n'

ALIAS_HEADER = "# alias.sh — sourced by ~/.bashrc\n"

BASHRC_HEADER = """\
# .bashrc
export PATH="$HOME/bin:$HOME/.local/bin:$PATH"
bin_exists() { command -v "$1" >/dev/null 2>&1; }
[ -f "$HOME/.aliases" ] && source "$HOME/.aliases"
"""

DOCKERFILE_TEMPLATE = """\
FROM debian:trixie
RUN apt-get update && apt-get install -y sudo curl git gettext
RUN useradd -m -s /bin/bash alex && echo "alex ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
USER alex
WORKDIR /home/alex
COPY --chown=alex:alex . /home/alex/dotgen
RUN mkdir -p /home/alex/.config/dotgen && \\
    cp /home/alex/dotgen/config/dotgen/secrets.env.template /home/alex/.config/dotgen/secrets.env && \\
    cd /home/alex/dotgen && bash setup.sh deploy
CMD ["/bin/bash"]
"""


def build_env(env: Environment, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    shim_text = OSShim(env.os).render()
    (out_dir / "os_shim.sh").write_text(shim_text)

    fragment = _merge_fragments(env)

    setup = SETUP_HEADER
    if fragment.setup:
        setup += "\n" + fragment.setup.rstrip("\n") + "\n\n"
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

    if fragment.secrets:
        _write_secrets_template(out_dir, fragment.secrets)

    if env.name == "debian-docker":
        (out_dir / "Dockerfile").write_text(DOCKERFILE_TEMPLATE)


def _write_secrets_template(out_dir: Path, secrets: frozenset[str]) -> None:
    lines = [
        "# dotgen secrets — fill and move to ~/.config/dotgen/secrets.env\n",
        "# single-line values only\n",
        "\n",
    ]
    for key in sorted(secrets):
        lines.append(f'# {DESCRIPTIONS.get(key, "")}\n{key}=""\n\n')
    dest_dir = out_dir / "config" / "dotgen"
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "secrets.env.template").write_text("".join(lines))


def build_all(out_root: Path) -> None:
    for name, env in ENVIRONMENTS.items():
        build_env(env, out_root / name)


_HEADER_FMT = "# --- {name} ---"


def _decorate(name: str, frag: Fragment) -> Fragment:
    header = _HEADER_FMT.format(name=name) + "\n"
    if not frag.setup:
        setup = ""
    else:
        indented = textwrap.indent(frag.setup.rstrip(), "  ")
        setup = textwrap.dedent(f"""\
{header}component_begin "{name}"
if (
  set -e
{indented}
); then
  component_end "{name}" 0
else
  _rc=$?; component_end "{name}" "$_rc"; exit "$_rc"
fi
        """).lstrip()

    alias = f"{header}{frag.alias}" if frag.alias else ""
    bashrc = f"{header}{frag.bashrc}" if frag.bashrc else ""
    return Fragment(setup=setup, alias=alias, bashrc=bashrc, configs=frag.configs, secrets=frag.secrets)


def _merge_fragments(env: Environment) -> Fragment:
    result = Fragment()
    for component in env.components:
        if component.applies_to(env):
            result = result.merge(_decorate(component.name, component.render(env)))
    return result
