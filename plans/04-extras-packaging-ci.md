# Plan 04 — macOS extras, opt-in components, packaging & CI

## Context

Plans 01–03 produced working bundles for all three environments with the named-important apps. This plan finalizes:

- macOS-only graphical app (Ghostty) with config
- An opt-in component (Postgres) registered but not in any default env list
- Tarball packaging so bundles are easy to `scp`
- Final `just ci` recipe and a brief README so the workflow is self-documenting
- End-to-end verification on the macOS host

## Pre-flight checks

Several plans deep — re-verify the structure hasn't drifted:

```bash
cd /Users/alex/repos/dotfiles_v2
just lint && just typecheck && just test       # baseline green
just build-all && just shellcheck              # bundles still valid

ls src/dotgen/components/                      # expect the full set from Plan 03
grep -E '^_(BASE|SHARED|FULL_ADDONS)' src/dotgen/environment.py   # confirm tuple naming
ls dist/macos/config/                          # expect: starship.toml, git/, claude/, helix/, aws/ (no ghostty/ yet)
```

If component composition has been refactored (e.g., `_SHARED`/`_FULL_ADDONS` renamed), update the wiring section below before editing.

Confirm the repo is still package-mgr-agnostic:

```bash
grep -rE 'apt-get|dnf install|brew install' src/dotgen/components/  # should return ZERO hits
```

If any component has fallen back to direct package-mgr calls, fix that to use `install_package`/`add_repo` from the shim before adding more.

## Tasks

### 1. `ghostty.py` — macOS only

- `applies_to`: `env.os is OS.MACOS`.
- `setup`: `brew install --cask ghostty` gated on `bin_exists ghostty`.
- `ConfigFile` at `~/Library/Application Support/com.mitchellh.ghostty/config`:
  ```
  font-family = UbuntuMonoNerdFont
  font-size = 14
  theme = default
  window-decoration = true
  audio-bell = false
  ```
  (Mirrors the v1 kitty config intent. Adjust theme name to one Ghostty ships with.)
- No bashrc contribution.

### 2. `postgres.py` — opt-in registry

- `applies_to`: returns `True` (the gating is at composition time — it's just not in any default `ENVIRONMENTS` tuple).
- `setup`:
  - macOS: `brew install postgresql@17`; appends `/opt/homebrew/opt/postgresql@17/bin` to PATH via bashrc.
  - debian: `add_repo apt pgdg https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main` + keyring; `install_package postgresql-17`.
  - fedora: official PGDG repo + `install_package postgresql17-server`.
- `bashrc`: prepend the version-specific bin dir to PATH (per-OS).

Document the opt-in in the README:

> Postgres is not part of any default environment. To include it, edit `src/dotgen/environment.py` and append `Postgres()` to the relevant environment's component tuple, then `just build <env>`.

### 3. Wire ghostty into macos env

```python
ENVIRONMENTS["macos"] = Environment(
    "macos", OS.MACOS, PkgMgr.BREW,
    components=_SHARED + _FULL_ADDONS + (Ghostty(),),
)
```

`Postgres()` deliberately stays out of any tuple here.

### 4. Tarball packaging in justfile

Add/finalize:

```
package env:    tar -C dist -czf dist/{{env}}.tar.gz {{env}}
package-all:    for e in debian fedora macos; do just package $e; done
build env:      uv run python -m dotgen build {{env}} && just package {{env}}
build-all:      uv run python -m dotgen build-all && just package-all
```

`just clean` keeps `rm -rf dist`. After `just build-all` the user has both `dist/<env>/` directories and `dist/<env>.tar.gz` files.

Also wire `just install env` as a local convenience: `bash dist/{{env}}/setup.sh`.

### 5. Final `just ci` recipe

```
ci:   just lint && just typecheck && just test && just build-all && just shellcheck
```

(Already added incrementally; this plan just confirms it ties everything together.)

### 6. README.md

Short — one screen. Cover:

- What this repo produces (bash bundles for fresh-machine bootstrap).
- How to build (`just build-all`).
- How to deploy: `scp dist/<env>.tar.gz host:`, `tar xzf <env>.tar.gz && bash <env>/setup.sh`.
- How to add a new environment (define in `environment.py`, choose components).
- How to add a new component (subclass + register + golden update).
- How to enable opt-in components (postgres example).
- Local dev loop (`just lint typecheck test`).

### 7. End-to-end verification (macOS host)

Run the full bundle locally and confirm idempotency on a second run.

### 8. Update goldens

Final snapshot regen — `UPDATE_GOLDEN=1 just test` — and review the full diff against Plan 03's goldens to ensure changes are explainable.

## Critical files

- `/Users/alex/repos/dotfiles_v2/src/dotgen/components/{ghostty,postgres}.py`
- `/Users/alex/repos/dotfiles_v2/src/dotgen/environment.py`
- `/Users/alex/repos/dotfiles_v2/justfile`
- `/Users/alex/repos/dotfiles_v2/README.md`
- `/Users/alex/repos/dotfiles_v2/tests/golden/`

## Verification

```bash
cd /Users/alex/repos/dotfiles_v2
just clean && just ci                   # full chain green
ls dist/                                # debian/ fedora/ macos/ + .tar.gz for each

# macOS end-to-end:
tar -C /tmp -xzf dist/macos.tar.gz
bash /tmp/macos/setup.sh
exec bash -l
for cmd in jq rg fd hx vim starship zoxide kubectl helm k9s claude uv cargo fnm go gcloud aws ghostty; do
  command -v "$cmd" >/dev/null && echo "OK $cmd" || echo "MISSING $cmd"
done
test -f "$HOME/Library/Application Support/com.mitchellh.ghostty/config"

# Idempotency:
bash /tmp/macos/setup.sh                # second run: no errors, no destructive changes

# Postgres opt-in smoke (sanity check the docs):
# Edit environment.py, append Postgres() to macos tuple, rebuild, install.
```

End-state: `dotfiles_v2` is a self-contained, type-checked, tested Python build system that produces deployable bash bundles for three OS targets, with an opt-in extension pattern for components like Postgres. All apps the user named are covered.
