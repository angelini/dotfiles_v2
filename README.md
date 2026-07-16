# dotfiles_v2

A Python build system that emits per-environment bash bundles for fresh-machine bootstrap. Target machines need zero deps — just `bash` and `curl`.

## Build

```bash
just build-all          # all envs → dist/<env>/ + dist/<env>.tar.gz
just build macos        # one env
just list               # known envs
just clean              # rm -rf dist
```

`just ci` runs the full chain: `lint typecheck test build-all shellcheck`.

## Deploy

```bash
scp dist/macos.tar.gz host:
ssh host 'tar xzf macos.tar.gz && bash macos/setup.sh deploy'
```

Or locally on the build host:

```bash
just install macos
```

## Secrets / PII

The tarball is safe to publish — PII (git identity, signing key, account IDs, tokens) is never embedded. Components reference secrets as `${VAR}` placeholders that are substituted at install time via `envsubst`, sourced from a per-machine file:

```
~/.config/dotgen/secrets.env
```

Before `setup.sh deploy`, populate that file using `dist/<env>/config/dotgen/secrets.env.template` as a checklist (it lists every key the bundle needs). Single-line `KEY="value"` per line. `setup.sh deploy` aborts if the file is missing.

Authoritative copy lives in your password manager; copy onto each new box once. Google model access uses `GEMINI_API_KEY`.

## Pi system

The Pi component installs the Pi CLI/packages, writes managed config under `~/.pi/agent`, and installs the sandbox wrapper. It also bundles a sanitized copy of the sibling `pi-angelini` repository into the artifact and syncs it to `~/repos/pi-angelini` during deploy. The bundle excludes `.git`, `node_modules`, lockfiles, caches, tests, and plan artifacts; Pi then loads it as the local package source `~/repos/pi-angelini`.

Managed Pi config includes Plannotator, the Supacode Pi extension, and the `supacode-cli` skill. Runtime state and secrets remain intentionally unmanaged: auth files, MCP OAuth tokens, package caches, sessions, memory DBs, Context7 caches, and usage databases are not copied.

On macOS, setup installs the Supacode app via the Homebrew cask.

## Layout

- `src/dotgen/` — package
  - `types.py`, `fragment.py`, `component.py`, `environment.py` — core types
  - `shim.py` — per-OS bash function library (`install_package`, `add_repo`, `download_bin`, …)
  - `render.py` — fragment merge + file emit
  - `bash.py` — quoting/section helpers
  - `components/<name>.py` — each `@dataclass(frozen=True)` implementing `Component`
  - `resources/` — static files copied into generated bundles
- `tests/golden/<env>/` — pinned bundle snapshots; refresh with `UPDATE_GOLDEN=1 just test`

## Add a new environment

Edit `src/dotgen/environment.py`:

```python
ENVIRONMENTS["alpine"] = Environment(
    "alpine", OS.ALPINE, PkgMgr.APK,
    components=_SHARED,
)
```

`OS.ALPINE` / `PkgMgr.APK` need adding to `types.py`, plus an entry in `_SHIMS` in `shim.py` implementing the 18 contract functions.

## Add a new component

1. Create `src/dotgen/components/foo.py`:

   ```python
   from dataclasses import dataclass
   from typing import TYPE_CHECKING
   from dotgen.bash import section
   from dotgen.fragment import Fragment

   if TYPE_CHECKING:
       from dotgen.environment import Environment

   @dataclass(frozen=True)
   class Foo:
       name: str = "foo"
       def applies_to(self, env: "Environment") -> bool: return True
       def render(self, env: "Environment") -> Fragment:
           return Fragment(setup=section("foo", "install_package foo\n"))
   ```

2. Register in `environment.py` by appending to the relevant tuple (`_BASE`, `_SHARED`, `_FULL_ADDONS`, or a specific env).
3. Refresh goldens: `UPDATE_GOLDEN=1 just test`. Review the diff.

## Opt-in components

`Postgres` is registered but not in any default `ENVIRONMENTS` tuple. To include it on (e.g.) macos:

```python
# src/dotgen/environment.py
from dotgen.components.postgres import Postgres
...
"macos": Environment(
    "macos", OS.MACOS, PkgMgr.BREW,
    components=_SHARED + _FULL_ADDONS + (Ghostty(), Postgres()),
),
```

Then `UPDATE_GOLDEN=1 just test && just build macos`.

## Local dev loop

```bash
just lint               # ruff
just typecheck          # ty
just test               # pytest (90 tests)
just fmt                # ruff format
```

`tests/test_shellcheck.py` runs `shellcheck` against every emitted bundle; skipped if shellcheck is not installed.
