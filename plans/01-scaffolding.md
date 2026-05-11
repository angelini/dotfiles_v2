> **Superseded — fedora removed in Plan 07.**

# Plan 01 — Project scaffolding & core abstractions

## Context

`dotfiles_v2` is a Python program that emits per-environment bash bundles (`setup.sh`, `alias.sh`, `.bashrc`, `os_shim.sh` + `config/`) for fresh-machine bootstrap. Target machines need zero deps. Build-time uses `uv`, `ruff`, `ty`, `pytest`, orchestrated by `Just`.

This plan stands up the empty skeleton: tooling, package layout, core type definitions, the renderer skeleton, and a Justfile. No real components yet — the goal is "type-checks, lints, tests pass, `just build-all` produces empty-but-valid bash bundles."

Three target environments will exist later: `debian` (apt, minimal VM), `fedora` (dnf, medium VM), `macos` (brew, full dev box). Plan 01 only registers their names with empty component lists.

## Pre-flight checks

(Plan 01 is the first step — only assumption is the repo dir exists.)

```bash
test -d /Users/alex/repos/dotfiles_v2 && ls /Users/alex/repos/dotfiles_v2
```

Expect: directory exists; only `plans/` inside.

## Tasks

### 1. uv project init + tooling config

- `pyproject.toml` — project name `dotgen`, requires-python ≥3.12, no runtime deps. Dev deps: `ruff`, `ty`, `pytest`. Tool config blocks for `[tool.ruff]` (line-length 100, select common rules) and `[tool.ty]` (strict on `src/`).
- `.python-version` → `3.12`
- `.gitignore` → `dist/`, `.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`
- `uv lock && uv sync` to materialize `.venv` and `uv.lock`

### 2. Justfile

```
default:        @just build-all
build env:      uv run python -m dotgen build {{env}}
build-all:      uv run python -m dotgen build-all
list:           uv run python -m dotgen list-envs
lint:           uv run ruff check src tests
fmt:            uv run ruff format src tests
typecheck:      uv run ty check src
test:           uv run pytest
clean:          rm -rf dist
ci:             just lint && just typecheck && just test && just build-all
```

(Tarball + shellcheck recipes added in Plan 04.)

### 3. Package skeleton

```
src/dotgen/
  __init__.py
  __main__.py            # delegates to cli.main()
  cli.py                 # argparse: build, build-all, list-envs
  types.py               # OS, PkgMgr StrEnums; Arch
  fragment.py            # ConfigFile, Fragment dataclasses + merge
  component.py           # Component Protocol
  environment.py         # Environment dataclass; ENVIRONMENTS = {debian,fedora,macos: empty}
  shim.py                # OSShim placeholder; render() returns empty shim with stub functions
  render.py              # build_env(env, out_dir), build_all(out_root)
  bash.py                # quote(), heredoc(), section(), argv(), guard_if_bin(), banner()
  components/__init__.py # COMPONENT_REGISTRY = {} for now
```

Key signatures (frozen dataclasses, fully typed):

```python
# fragment.py
@dataclass(frozen=True)
class ConfigFile:
    dest: str
    content: str
    mode: int = 0o644

@dataclass(frozen=True)
class Fragment:
    setup: str = ""
    alias: str = ""
    bashrc: str = ""
    configs: tuple[ConfigFile, ...] = ()
    def merge(self, other: "Fragment") -> "Fragment": ...

# component.py
class Component(Protocol):
    name: str
    def applies_to(self, env: "Environment") -> bool: ...
    def render(self, env: "Environment") -> Fragment: ...

# environment.py
@dataclass(frozen=True)
class Environment:
    name: str
    os: OS
    pkg_mgr: PkgMgr
    components: tuple[Component, ...] = ()
ENVIRONMENTS: dict[str, Environment] = {
    "debian": Environment("debian", OS.DEBIAN, PkgMgr.APT),
    "fedora": Environment("fedora", OS.FEDORA, PkgMgr.DNF),
    "macos":  Environment("macos",  OS.MACOS,  PkgMgr.BREW),
}
```

### 4. Renderer skeleton

- `render.build_env(env, out_dir)`:
  - `out_dir.mkdir(parents=True, exist_ok=True)`
  - writes `os_shim.sh` from `OSShim(env.os).render()`
  - merges fragments (will be empty for now), writes `setup.sh` (header + body + footer), `alias.sh`, `.bashrc`
  - writes `config/` if any ConfigFiles present
- Headers/footers as module-level constants. `setup.sh` header: `#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/os_shim.sh"
update_pkg_index`
- `bashrc` header: PATH prelude (`~/bin`, `~/.local/bin`) + `[ -f "$HOME/.aliases" ] && source "$HOME/.aliases"`

### 5. CLI

`python -m dotgen build <env>`, `build-all`, `list-envs`. Exit non-zero on unknown env. Uses `argparse`.

### 6. Tests

- `tests/test_bash_helpers.py` — `quote()` round-trips special chars; `heredoc()` produces unique tag; `section()` adds banner.
- `tests/test_render_skeleton.py` — `build_env(ENVIRONMENTS["debian"], tmp_path)` produces all 4 files, each `bash -n` clean.

### 7. Stub OS shim

`shim.py` emits, for every OS, a shim defining each function in the contract as a no-op or `echo "TODO"`-style stub. The function *names* are the contract; bodies get filled in Plan 02. This lets the renderer succeed and Plan 02 only changes bodies, not call sites.

Function names (must all exist in every shim from this plan onward):
`detect_os`, `detect_arch`, `bin_exists`, `pkg_installed`, `install_package`, `install_packages`, `add_repo`, `update_pkg_index`, `service_enable`, `download_bin`, `download_tar_bin`, `link_file`, `ensure_dir`, `install_config`, `log`, `error`, `ask`.

## Critical files

- `/Users/alex/repos/dotfiles_v2/pyproject.toml`
- `/Users/alex/repos/dotfiles_v2/justfile`
- `/Users/alex/repos/dotfiles_v2/src/dotgen/{types,fragment,component,environment,bash,render,shim,cli}.py`
- `/Users/alex/repos/dotfiles_v2/tests/test_bash_helpers.py`
- `/Users/alex/repos/dotfiles_v2/tests/test_render_skeleton.py`

## Verification

```bash
cd /Users/alex/repos/dotfiles_v2
just lint             # ruff clean
just typecheck        # ty clean
just test             # pytest green
just build-all        # produces dist/{debian,fedora,macos}/{setup.sh,alias.sh,.bashrc,os_shim.sh}
for f in dist/*/*.sh dist/*/.bashrc; do bash -n "$f" || exit 1; done
```

All four files exist per env; each is `bash -n` clean. shim functions are stubs but callable.
