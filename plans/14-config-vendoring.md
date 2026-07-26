# Plan 14: Directory Vendoring for Component Configs

This plan adds a first-class way for a component to vendor an entire on-disk directory into
`dist/<env>/config/` and onto the target, instead of inlining each file as a Python string. It
generalizes the bespoke `pi-angelini` mechanism (`_pi_angelini_configs` / `_install_pi_angelini`
in `pi_agent.py`) into a reusable `VendorDir` primitive, adds filtering, and supports overlaying a
secrets-templated file on top of a vendored tree.

## Context

Two config-shipping patterns exist today, both routed through `ConfigFile.content: str`:

1. **Inline strings** — content built in Python (`_SETTINGS_JSON`) or read into a string at import
   time via `_resource_text` (`pi_agent.py:75`). Each file is one `ConfigFile`, emitted by
   `render.build_env` with `write_text` (`render.py:105-109`).
2. **Build-time repo walk** — `_pi_angelini_configs` (`pi_agent.py:112`) `rglob`s a sibling repo,
   excludes a hardcoded set, and returns **one `ConfigFile` per file**, each read fully into memory.
   `_install_pi_angelini` (`pi_agent.py:493`) then hand-rolls the deploy-time copy with a
   `DOTGEN_MODE=diff` branch and `.git`-preservation.

Adding a Claude config tree (`~/.claude/{agents,skills,commands,settings.json,CLAUDE.md}`, plus
per-skill subtrees) via either pattern is unworkable: it is dozens-to-hundreds of files, several
non-text, and the source of truth is the directory, not any single Python literal. Pattern 2 is the
right shape but is welded into `PiAgent`, holds every file in memory as a separate `ConfigFile`, and
its filter is a fixed constant.

## Design Goals

1. A component points at a **directory**; the build vendors the (filtered) tree into
   `dist/<env>/config/<dest>/` and the deploy step copies it to the target.
2. Filtering is declarative and reusable — skip VCS/build/dependency artifacts (`.git`,
   `node_modules`, `dist/`) by preset, or allow-list only wanted files.
3. The vendored tree is tracked **as a directory**, not as N individually-inlined files. Goldens
   record a manifest (path + mode + content hash), not each file's bytes.
4. A component can **layer** on top of a vendored tree: vendor first, then overlay a
   secrets-templated file into the same output location afterwards.
5. Secrets are never vendored. Filtering supports allow-listing precisely so credential/runtime
   junk cannot be swept in.
6. `pi-angelini` migrates onto the new primitive; the bespoke walk and installer are deleted.

## The `VendorDir` Primitive

Add a frozen, hashable, mergeable directive that represents *one directory to copy*, distinct from
`ConfigFile` (which stays for single files / templates).

```python
# src/dotgen/vendor.py
from dataclasses import dataclass, field
from pathlib import Path

GIT_ARTIFACTS = frozenset({".git", ".gitignore"})
NODE_ARTIFACTS = frozenset({"node_modules", "package-lock.json"})
PY_ARTIFACTS = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "*.egg-info"})
BUILD_ARTIFACTS = frozenset({"dist", "build", "target", ".next"})

@dataclass(frozen=True)
class VendorDir:
    source: Path                                   # absolute dir on the build host
    dest: str                                      # path under dist/<env>/config/
    exclude_dirs: frozenset[str] = frozenset()     # dir names pruned anywhere in the tree
    exclude_globs: tuple[str, ...] = ()            # rel-path globs to drop (e.g. "dist/**")
    include_globs: tuple[str, ...] = ()            # if set: ALLOW-LIST — only matches are vendored
    preserve_modes: bool = True                    # keep the source exec bit, else 0o644
```

- **Deny-list mode** (default): a file is vendored unless any path part is in `exclude_dirs` or its
  relative path matches an `exclude_globs` entry. This is today's `pi-angelini` behavior,
  parameterized.
- **Allow-list mode** (`include_globs` set): a file is vendored only if it matches an
  `include_globs` entry (deny rules still apply on top). Use this for anything near secrets — e.g.
  Claude config where `~/.claude` also holds `.credentials.json` and `history.jsonl`.
- "Vendor build or non-build assets" is expressed purely through the filter: pass
  `exclude_dirs=GIT_ARTIFACTS | BUILD_ARTIFACTS` to skip built output, or omit `BUILD_ARTIFACTS` to
  ship it.
- The source root is chosen by the component (allowing a `DOTGEN_*_ROOT` env override, mirroring
  `DOTGEN_PI_ANGELINI_ROOT` at `pi_agent.py:106`), so the same directive works against an in-repo
  `resources/` tree or a sibling repo.

### Fragment integration

Add a `vendors` field; merge and decorate pass it through unchanged.

```python
# fragment.py
@dataclass(frozen=True)
class Fragment:
    setup: str = ""
    alias: str = ""
    bashrc: str = ""
    configs: tuple[ConfigFile, ...] = ()
    vendors: tuple[VendorDir, ...] = ()          # NEW
    secrets: frozenset[str] = frozenset()

    def merge(self, other):
        return Fragment(
            ...,
            vendors=self.vendors + other.vendors,
            ...,
        )
```

`render._decorate` copies `vendors` through alongside `configs` (no shell decoration — vendors emit
no setup of their own; see below).

## Build-Time Emit

`render.build_env` gains a vendor pass that runs **before** the `configs` pass, so a templated
`ConfigFile` can be overlaid on top of a vendored tree (Goal 4):

```python
# render.py build_env, after the configs block is reordered
for v in fragment.vendors:
    _vendor_dir(v, config_dir / v.dest)          # walk + copy filtered tree (binary-safe copyfile)
for cf in fragment.configs:
    ...                                          # existing single-file emit, can land inside a vendor dest
```

- `_vendor_dir` walks `source` with the filter, `shutil.copyfile`s each kept file (bytes, so
  non-text assets work), and applies the mode (`0o755` if the source is executable and
  `preserve_modes`, else the file's mode / `0o644`).
- A missing `source` raises `FileNotFoundError` (same fail-loud behavior as `_pi_angelini_configs`
  today), unless the component guarded it via `applies_to`.

## Deploy-Time Copy (Shim)

Replace the per-file `install_config` lines and the bespoke `_install_pi_angelini` with one shim
helper that copies a whole directory idempotently and supports `DOTGEN_MODE=diff`.

```
install_config_dir <src_dir> <dst_dir>
```

- `deploy` mode: recursive copy of `<src_dir>` → `<dst_dir>`, creating parents, overwriting managed
  files, preserving modes. Idempotent (re-running `setup.sh` on a finished box is a no-op).
- `diff` mode: print `+ COPY <dst>` when absent, `~ SYNC <dst>` when the trees differ, nothing when
  equal — matching the existing `_install_pi_angelini` diff output.

Because filtering already happened at build time, the deploy copy ships the whole (already-clean)
`dist/config/<dest>` tree — no filter logic in bash.

This extends the shim contract, so per `CLAUDE.md`: add `install_config_dir` to `SHIM_FUNCTIONS`,
add a body to all three `_SHIM_*` strings, and the parity test in `test_shim.py` guards drift.

### Overlaying a templated secrets file

The layering the request calls for — "vendor first, then apply a templated file afterwards" — is
expressed as a vendor directive plus a following `install_config_template` line, both in the
component. Secrets stay out of `dist/` (`CLAUDE.md` invariant); substitution happens on the target
at deploy time:

```python
Fragment(
    vendors=(VendorDir(source=root, dest="claude", exclude_dirs=GIT_ARTIFACTS | NODE_ARTIFACTS),),
    configs=(ConfigFile(dest="claude/local.env.template", content=_LOCAL_ENV_TEMPLATE),),
    setup=section("claude", (
        'install_config_dir "$DIR/config/claude" "$HOME/.claude"\n'
        'install_config_template "$DIR/config/claude/local.env.template" '
        '"$HOME/.claude/local.env" \'GIT_USER_NAME GIT_USER_EMAIL\'\n'
    )),
    secrets=frozenset({"GIT_USER_NAME", "GIT_USER_EMAIL"}),
)
```

Deploy order on the target: `install_config_dir` lays down the tree, then
`install_config_template` writes the substituted file on top of it. The `.template` file is inert
until substituted, so it is safe to vendor.

## Testing: Manifest, Not Per-File Goldens

Goal 3 — track vendored output as files, not inlined content. But vendored sources are **mutable
external repos** (`pi-angelini`, `claude-config`), so their content must not be hashed into
committed goldens: that would churn the golden on every external-repo change and differ per machine.
Split the concern:

- **Deterministic content → golden manifest.** New `tests/golden/<env>/config-manifest.txt`: sorted
  `mode  sha256  relpath` for every **inline `ConfigFile`** under `config/` (content is built in
  Python, fully reproducible). Vendored dests are recorded as a **single directory line**
  (`dir  <dest>`), not per-file hashes — enough to catch "a vendor stopped/started emitting" without
  binding the golden to external content. New test in `test_render_snapshot.py`, same
  `UPDATE_GOLDEN=1` / auto-create-and-skip protocol as the existing snapshot test.
- **Vendoring logic → fixture-based unit tests.** `VendorDir` filtering, mode preservation, and
  allow/deny behavior are tested against a `tests/fixtures/vendor_src/` tree checked into the repo —
  deterministic and independent of `~/repos/*`. This is where the filter guarantees live.

Note the pre-existing coupling this keeps: because vendoring is fail-loud, `build_env` and any test
that builds a real env still require the external repos to exist on the build host (already true for
`pi-angelini`). Fixture tests do not.

Component-level tests (`test_components.py`):

- `VendorDir` filtering: deny-list prunes `exclude_dirs` at any depth; `exclude_globs` drops
  matches; allow-list mode vendors only `include_globs` matches.
- Executable bit is preserved when `preserve_modes` is set.
- A secret-shaped filename (`.credentials.json`, `secrets.env`) is excluded when not allow-listed —
  a guard test for Goal 5.
- `PiAgent` still emits the `pi-angelini` tree at the same dests after migration (regression).

## Component Changes

### `src/dotgen/components/pi_agent.py` (migration)

- Delete `_pi_angelini_configs`, `_PI_ANGELINI_EXCLUDED_*`, and `_install_pi_angelini`.
- Emit `VendorDir(source=_pi_angelini_root(), dest="pi-angelini", exclude_dirs=GIT_ARTIFACTS |
  NODE_ARTIFACTS | PY_ARTIFACTS | {".pi-lens", ".pi-subagents", ".serena", "dist"},
  exclude_globs=("package-lock.json", "pi-system-audit-plan.md", "*.test.ts"))`.
- Replace the `_install_pi_angelini` call with `install_config_dir "$DIR/config/pi-angelini"
  "$HOME/repos/pi-angelini"`. (Note: the old installer preserved a target `.git`; `install_config_dir`
  overwrites managed files but does not delete unmanaged ones, so a target `.git` survives. Confirm
  in the deploy smoke test; if strict `.git` preservation is required, keep it as an explicit
  decision below.)
- The `claude-pipeline` agent set and supacode skill currently read via `_resource_text` + per-file
  `install_config` can optionally move under a `resources/pi_agent` `VendorDir`; out of scope for
  this plan unless it falls out cheaply.

### New: `src/dotgen/components/claude_code_config.py` (motivating use case)

Source is the **external repo `~/repos/claude-config`** (pure option B), overridable via
`DOTGEN_CLAUDE_ROOT`. The repo does not exist yet; it will be created before this component is built.

- Vendors `VendorDir(source=_claude_root(), dest="claude", exclude_dirs=GIT_ARTIFACTS | NODE_ARTIFACTS
  | PY_ARTIFACTS)`. Allow-list mode is unnecessary because `~/repos/claude-config` is a curated repo
  (unlike a live `~/.claude`, which holds `.credentials.json` and history) — deny-listing VCS and
  dependency artifacts is enough. If the source is ever pointed at a live `~/.claude`, switch to
  `include_globs=("agents/**", "skills/**", "commands/**", "settings.json", "CLAUDE.md")`.
- Emits `install_config_dir "$DIR/config/claude" "$HOME/.claude"`; optional templated `local.env`
  overlay as shown above.
- **Fail-loud, matching `pi-angelini`:** vendoring a missing source raises `FileNotFoundError`, so
  once registered in `_SHARED` the build requires `~/repos/claude-config` to exist. Create and
  populate the repo, then register in `registry.py`, add the unit test, and refresh goldens in the
  same commit.

## Critical Files

- `src/dotgen/fragment.py` — `Fragment.vendors`, merge.
- `src/dotgen/vendor.py` — `VendorDir`, artifact presets, filter predicate.
- `src/dotgen/render.py` — vendor pass before configs pass; `_vendor_dir` walk/copy.
- `src/dotgen/shim.py` — `install_config_dir` in `SHIM_FUNCTIONS` + all three `_SHIM_*` bodies.
- `src/dotgen/components/pi_agent.py` — migrate off the bespoke walk/installer.
- `src/dotgen/components/claude_code_config.py` + `registry.py` — new component.
- `tests/test_shim.py` — parity for the new helper.
- `tests/test_components.py` — filtering, modes, secret-exclusion, pi-angelini regression.
- `tests/test_render_snapshot.py` — config-manifest golden + test.
- `tests/golden/<env>/config-manifest.txt` — new goldens.

## Verification

- `just ci` (lint + typecheck + test + build-all + shellcheck).
- `grep -rE 'apt-get|brew install' src/dotgen/components/` returns zero hits (shim invariant).
- `UPDATE_GOLDEN=1 just test`, then read the manifest + bash diffs before committing.
- Deploy smoke (Debian VM via `just test-vm debian`):
  - vendored `~/repos/pi-angelini` matches `dist/config/pi-angelini` and excludes `.git`/`node_modules`.
  - `~/.claude/{agents,skills,commands}` present; no `.credentials.json` / history / secrets vendored.
  - templated `local.env` (if used) has substituted values and no `${...}` placeholders.
  - re-run `setup.sh deploy` is a no-op (idempotency).

## Decisions

1. `VendorDir` is a distinct Fragment primitive, not an overloaded `ConfigFile` — copying a tree and
   emitting a single file have different emit and test semantics.
2. Filtering is **declarative** (frozensets + glob tuples), not a predicate callable, so directives
   stay hashable and manifests stay reproducible across builds.
3. Goldens hash only **deterministic inline config** content; **externally vendored trees are
   mutable**, so they are recorded as a directory presence line in the manifest and their filtering
   is verified via checked-in fixtures, never by hashing `~/repos/*` content into a golden.
4. Filtering happens at **build time**; the deploy-time `install_config_dir` copies the already-clean
   tree, keeping bash filter-free.
5. Secrets never enter `dist/`; layering a secrets file is vendor-then-`install_config_template` on
   the target, using the existing whitelist mechanism.
6. Claude config vendors from the curated repo `~/repos/claude-config` in **deny-list mode** (VCS +
   dependency artifacts only). Allow-list mode is reserved for the case where a source is a live
   config dir mixing credentials and runtime state (e.g. `~/.claude` directly).
7. `install_config_dir` **overlays** — it writes managed files and never deletes unmanaged ones. It
   never wipes the target dir. Consequences:
   - A pre-existing target `.git` is preserved with no special-casing — it is simply an unmanaged
     file the copy never touches. "Preserve git" is therefore not a feature; it falls out of not
     deleting. The only strategy that would lose `.git` is wipe-and-replace, which is rejected.
   - Wipe-and-replace is rejected outright: vendored tool-config dirs interleave managed config with
     credentials, history, caches, and build/runtime state (`~/.claude/.credentials.json`,
     `history.jsonl`, pi-angelini `.git`) that a full replace would destroy.
   - Overlay's one weakness — a file we stop shipping lingers on the target — is acceptable for tool
     configs. If removals must propagate, upgrade to manifest-scoped sync: write a
     `<dst>/.dotgen-manifest` of managed relpaths on deploy, and next deploy delete only
     previously-managed files absent from the new manifest. Unmanaged files are never in the
     manifest, so they are never deletion candidates. Deferred until a concrete need appears.
   - The allow-list filter, not the copy strategy, defines "managed"; that boundary is where safety
     lives.

## Scope

This primitive is for **local tool-config directories** (`~/.claude`, `~/.pi`, pi-angelini, and
similar), not for cloning or syncing development repositories (e.g. `platform`). Target dirs are
expected to mix a small managed config set with local secrets/state, which is why overlay +
allow-list is the model and wipe-and-replace is rejected.
