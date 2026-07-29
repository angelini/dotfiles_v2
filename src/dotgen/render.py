import hashlib
import os
import shutil
import textwrap
from pathlib import Path, PurePosixPath
from typing import NoReturn

from dotgen.artifact import ArtifactBuilder, ProductionArtifactBuilder
from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.registry import ENVIRONMENTS
from dotgen.secrets import DESCRIPTIONS
from dotgen.shim import OSShim
from dotgen.vendor import VendorDir

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
  if [ "$(id -u)" -eq 0 ]; then
    error "deploy must run as a regular user, not root"
    exit 2
  fi
  if ! bin_exists sudo; then
    error "deploy requires sudo"
    exit 2
  fi
  if ! sudo -v; then
    error "unable to authenticate with sudo"
    exit 2
  fi
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
case $- in
  *i*) ;;
  *) return ;;
esac

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


def build_env(env: Environment, out_dir: Path, *, artifact_builder: ArtifactBuilder | None = None) -> None:
    if out_dir.exists():
        try:
            shutil.rmtree(out_dir)
        except OSError as exc:
            raise OSError(f"failed to clean build output {out_dir}: {exc}") from exc
    out_dir.mkdir(parents=True)

    shim_text = OSShim(env.os).render()
    (out_dir / "os_shim.sh").write_text(shim_text)

    fragment = _merge_fragments(env)

    if fragment.artifacts:
        if artifact_builder is None:
            with ProductionArtifactBuilder() as production_builder:
                production_builder.materialize(fragment.artifacts, out_dir)
        else:
            artifact_builder.materialize(fragment.artifacts, out_dir)

    setup = SETUP_HEADER
    if fragment.setup:
        setup += "\n" + fragment.setup.rstrip("\n") + "\n\n"
    setup += SETUP_FOOTER
    (out_dir / "setup.sh").write_text(setup)

    alias_text = ALIAS_HEADER + (fragment.alias + "\n" if fragment.alias else "")
    (out_dir / "alias.sh").write_text(alias_text)

    bashrc_text = BASHRC_HEADER + (fragment.bashrc + "\n" if fragment.bashrc else "")
    (out_dir / ".bashrc").write_text(bashrc_text)

    if fragment.configs or fragment.vendors:
        config_dir = out_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        for v in fragment.vendors:
            _vendor_dir(v, config_dir / v.dest)
        for cf in fragment.configs:
            dest = config_dir / cf.dest
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(cf.content)
            dest.chmod(cf.mode)

    if fragment.secrets:
        _write_secrets_template(out_dir, fragment.secrets)

    if env.name == "debian-docker":
        (out_dir / "Dockerfile").write_text(DOCKERFILE_TEMPLATE)


def _raise(err: OSError) -> NoReturn:
    raise err


def _vendor_dir(v: VendorDir, dest_dir: Path) -> None:
    if not v.source.is_dir():
        raise FileNotFoundError(f"vendor source not found: {v.source}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    for parent, dirs, files in os.walk(v.source, onerror=_raise):
        dirs[:] = sorted(d for d in dirs if not v.prunes_dir(d))
        parent_path = Path(parent)
        for name in sorted(files):
            src = parent_path / name
            rel = PurePosixPath(src.relative_to(v.source).as_posix())
            if not v.vendors_path(rel):
                continue
            dest = dest_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            dest.chmod(0o755 if v.preserve_modes and src.stat().st_mode & 0o111 else 0o644)


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


def build_all(out_root: Path, *, artifact_builder: ArtifactBuilder | None = None) -> None:
    if artifact_builder is not None:
        for name, env in ENVIRONMENTS.items():
            build_env(env, out_root / name, artifact_builder=artifact_builder)
        return
    with ProductionArtifactBuilder() as production_builder:
        for name, env in ENVIRONMENTS.items():
            build_env(env, out_root / name, artifact_builder=production_builder)


def required_secrets(env: Environment) -> frozenset[str]:
    return _merge_fragments(env).secrets


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
    return Fragment(
        setup=setup,
        alias=alias,
        bashrc=bashrc,
        configs=frag.configs,
        vendors=frag.vendors,
        artifacts=frag.artifacts,
        secrets=frag.secrets,
    )


def _merge_fragments(env: Environment) -> Fragment:
    result = Fragment()
    for component in env.components:
        if component.applies_to(env):
            result = result.merge(_decorate(component.name, component.render(env)))
    return result


def config_manifest(env: Environment) -> str:
    fragment = _merge_fragments(env)
    lines = [f"{cf.mode:04o}  {hashlib.sha256(cf.content.encode()).hexdigest()}  {cf.dest}" for cf in fragment.configs]
    lines += [f"dir  {v.dest}" for v in fragment.vendors]
    return "".join(f"{line}\n" for line in sorted(lines))
