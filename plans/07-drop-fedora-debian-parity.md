> **Superseded — fedora removed in Plan 07.**

# Plan 07 — Drop Fedora, bring Debian to feature parity with macOS (minus GUI)

## Context

The repo currently ships three deployment targets: `debian`, `fedora`, `macos`. Maintaining two Linux flavors costs ~15–20% of component LOC in OS-branching alone (per-OS package-name dicts, two repo-config dialects, three-implementation shim parity). Most actual Linux usage will be Debian/Ubuntu (WSL, OrbStack, Codespaces, cloud images). Fedora's value is mostly defensive — keeping a second flavor honest — and that's not worth the carrying cost for a personal-bootstrap repo.

New policy:

- **Two targets only**: `debian` and `macos`.
- **Feature parity**: every cross-platform component is registered for both envs.
- **GUI carve-out**: components that need a graphical desktop session stay macOS-only. Today that's `Ghostty` (terminal emulator) and `Zed` (editor). Everything else — including `Fonts` (used by terminal renderers and TUI tools like starship) — goes to both envs.

This plan is staged so each phase is independently mergeable, leaves the tree green, and produces at most one localized golden diff to review.

## Phase ordering rationale

Two orderings were considered (drop-Fedora-first vs. add-Debian-first). Add-Debian-first wins because dropping Fedora first temporarily removes our only cross-platform validation surface, and adding Debian paths first is purely additive (no behavior change, no golden churn). The phase boundaries below also keep golden regeneration confined to **one** phase against **one** platform.

## Pre-flight

```bash
just ci                                                              # baseline green
grep -rE 'apt-get|dnf install|brew install' src/dotgen/components/   # zero hits invariant
```

Read before starting:

- `src/dotgen/registry.py` — current `_BASE` / `_SHARED` / `_FULL_ADDONS` / `_LAST` composition.
- `src/dotgen/shim.py` — confirm `add_repo apt`, `install_script`, `download_tar_bin`, `install_package` cover everything Phase 1 needs (no shim extension required for any component below).
- `tests/test_components.py:221` — `test_environment_component_distribution` is the parity canary that gates Phase 2.

## Phase 1 — Add Debian paths to cross-platform components (additive)

**Goal**: every non-GUI component's `_BY_OS` dict has an `OS.DEBIAN` entry that produces working bash. No registry change. No golden change.

Components to touch (all in `src/dotgen/components/`):

- **`aws.py`** — rename `_SETUP_FEDORA` → `_SETUP_LINUX` (the curl-zip installer is arch-portable). Prepend `install_package unzip` to the helper body. Add `OS.DEBIAN: _SETUP_LINUX` to `_SETUP_BY_OS`.
- **`fonts.py`** — add `OS.DEBIAN` entry. apt has `fonts-ubuntu`; Nerd-Font has no apt package, so download a pinned tarball:
  ```
  install_packages fonts-ubuntu fontconfig xz-utils
  # idempotent download of UbuntuMono.tar.xz from a pinned nerd-fonts release
  # extract *.ttf into ~/.local/share/fonts/, then fc-cache -f
  ```
  Pin the Nerd-Fonts release to a digest/tag (per "pin large external artifacts" rule).
- **`gcloud.py`** — add `OS.DEBIAN` setup using the official APT repo:
  ```
  add_repo apt google-cloud-sdk \
    "deb [signed-by=/etc/apt/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    "https://packages.cloud.google.com/apt/doc/apt-key.gpg"
  update_pkg_index
  install_package google-cloud-cli
  ```
  Extend `_BASHRC` source-loop to include `/usr/lib/google-cloud-sdk/path.bash.inc` and `/usr/lib/google-cloud-sdk/completion.bash.inc`.
- **`go_lang.py`** — add `OS.DEBIAN: ("curl", "git", "make", "bison", "gcc", "libc6-dev")` to `_DEPS_BY_OS`.

Tests (`tests/test_components.py`):

- Update `test_go_lang_only_fedora_macos` (line 208) to also assert `GoLang().applies_to(ENVIRONMENTS["debian"])` is now `True`.
- Add Debian-side assertions in `test_python_tools_per_os`, `test_fonts_installs_ubuntu_nerd`, and the `aws` / `gcloud` tests so the new paths are covered.

**Verify**:
```bash
just lint && just typecheck && just test                             # green; goldens unchanged
grep -rE 'apt-get|dnf install|brew install' src/dotgen/components/   # still zero
```

## Phase 2 — Register parity for Debian; remove Zed from Linux

**Goal**: Debian env composition matches macOS minus GUI. `Zed` becomes macOS-only. **This phase produces the only large golden diff** (Debian only).

`src/dotgen/registry.py`:

- Change Debian env to `_SHARED + (Rust(), NodeFnm(), GoLang(), Gcloud(), Aws(), Fonts()) + _LAST` (no `Zed()`).
- macOS and Fedora envs **unchanged** in this phase. Verify their goldens are byte-identical post-phase.

`src/dotgen/components/zed.py`:

- Drop `OS.DEBIAN` from `_SETUP_BY_OS` so `applies_to` (which is `env.os in _SETUP_BY_OS`) excludes Debian. `_SETUP_BY_OS` becomes `{OS.MACOS, OS.FEDORA}` for now — Fedora gets stripped in Phase 3.

Tests (`tests/test_components.py`):

- Rewrite `test_environment_component_distribution` (line 221): the `full_only` set should drop `zed`; `debian_names` should now include `aws`, `fonts`, `gcloud`, `go_lang`, `rust`, `node_fnm`. Keep the `ghostty` exclusion check.
- Rewrite `test_zed_fedora_macos_only_and_emits_configs` (line 258) to assert Zed is macOS+Fedora only (Fedora removal happens in Phase 3, not here).

Goldens:

```bash
UPDATE_GOLDEN=1 just test                                            # regenerate
git diff tests/golden/debian/                                        # READ THIS DIFF — only review point on user-visible bash
git status tests/golden/fedora/ tests/golden/macos/                  # must show no changes
```

**Verify**: `just ci` green; Fedora and macOS goldens untouched; Debian setup.sh now installs the full parity set minus Zed.

## Phase 3 — Drop Fedora (atomic across types, shim, registry, components, tests)

**Goal**: a single coherent change removing every Fedora reference. Must land as one commit because removing `OS.FEDORA` from `types.py` before stripping fedora dict keys causes `KeyError` at module-import time during test collection.

Files to edit (all changes in one commit):

- `src/dotgen/types.py:6` — delete `FEDORA = "fedora"`. `src/dotgen/types.py:11` — delete `DNF = "dnf"`.
- `src/dotgen/shim.py:254-326` — delete `_SHIM_FEDORA` block; remove its entry from the `_SHIMS` dict around line 402.
- `src/dotgen/registry.py:57` — delete the `"fedora": Environment(...)` entry from `ENVIRONMENTS`.
- `src/dotgen/vm.py:288` — delete `"fedora": _OrbBackend` entry.
- Per-component fedora strip — delete the `OS.FEDORA` key (and any helper consts only it referenced) in each:
  - `aws.py:38` (and rename done in Phase 1 means just a dict key removal)
  - `core_utils.py:20`
  - `fonts.py:9`
  - `gcloud.py` — drop `_FEDORA_REPO`, `_SETUP_FEDORA`, the fedora dict key, and the fedora `path.bash.inc` line in `_BASHRC` (`/usr/lib64/...`)
  - `gh.py:19`
  - `go_lang.py:9`
  - `helix.py:26` — `_XZ_PKG` becomes `{OS.DEBIAN: "xz-utils"}`
  - `kubectl.py:78`
  - `postgres.py` — drop `_FEDORA_REPO`, `_SETUP_FEDORA`, the fedora keys in both `_SETUP_BY_OS` and `_BASHRC_BY_OS` (postgres registration remains out of scope, but the fedora *constants* must go since `OS.FEDORA` is being removed)
  - `python_tools.py:10`
  - `zed.py` — drop `OS.FEDORA` from `_SETUP_BY_OS`
- `tests/golden/fedora/` — delete the directory.
- `tests/test_components.py` — delete or rewrite every fedora reference: lines 57, 73–76, 109–111, 143–147, 199–204, 208–210, 223–227, 229, 235, 243, 251–254, 261–268, 291, 303, 311. Most are list-shrink or `for env_name in ("debian", "fedora", "macos")` → `("debian", "macos")`.
- `tests/test_vm_integration.py:22,26,27` — drop fedora image and timeout entries.
- `tests/test_shim.py:64` — drop the `"dnf "` parity check.
- `justfile:36` — comment `# env: debian | macos`.
- `plans/01-*.md` … `plans/06-*.md` — historical docs; flag fedora references with a small "**Superseded — fedora removed in Plan 07.**" note at the top of each, but do not rewrite the bodies.

**Verify**:
```bash
rg -n 'fedora|FEDORA|dnf|DNF' src/ tests/ justfile           # zero hits
just ci                                                              # green
git diff tests/golden/debian/ tests/golden/macos/                    # must be empty
```

## Phase 4 — Collapse `_BASE` / `_SHARED` / `_FULL_ADDONS`

**Goal**: with only two envs left, the three-tier registry structure is dead weight. Pure refactor — **must produce zero golden diff**.

`src/dotgen/registry.py`:

- Flatten to two tuples:
  - `_SHARED: tuple[Component, ...] = (BashBase(), CoreUtils(), Helix(), Starship(), Zoxide(), Kubectl(), PythonTools(), ClaudeCode(), Gh(), GitSigning(), Rust(), NodeFnm(), GoLang(), Gcloud(), Aws(), Fonts())`
  - `_MACOS_GUI: tuple[Component, ...] = (Ghostty(), Zed())`
  - `_LAST` unchanged.
- `ENVIRONMENTS = { "debian": Environment(..., components=_SHARED + _LAST), "macos": Environment(..., components=_SHARED + _MACOS_GUI + _LAST) }`.

`tests/test_components.py:test_environment_component_distribution`:

- Simplify to assert `_SHARED ⊆ debian_names ∩ macos_names` and `_MACOS_GUI ∩ debian_names == ∅`.

**Verify**:
```bash
just ci
git diff tests/golden/                                               # must be empty
```

## Phase 5 — VM verification

```bash
just test-vm debian
just test-vm macos
```

If either fails, the failure is real (not stale fixtures, since goldens were verified clean in Phase 4).

## Critical files

Modified across phases:

- `src/dotgen/registry.py` (Phases 2, 3, 4)
- `src/dotgen/types.py` (Phase 3)
- `src/dotgen/shim.py` (Phase 3)
- `src/dotgen/vm.py` (Phase 3)
- `src/dotgen/components/{aws,fonts,gcloud,go_lang}.py` (Phase 1, 3)
- `src/dotgen/components/{zed,helix,gh,kubectl,python_tools,core_utils,postgres}.py` (Phase 2 zed-only, Phase 3 the rest)
- `tests/test_components.py` (Phases 1, 2, 3, 4)
- `tests/test_vm_integration.py`, `tests/test_shim.py` (Phase 3)
- `tests/golden/debian/` (Phase 2 regeneration)
- `tests/golden/fedora/` (Phase 3 deletion)
- `justfile` (Phase 3 comment)

Reused without modification:

- `add_repo apt <id> <line> <key_url>` (shim) — gcloud, gh on Debian.
- `install_script` (shim) — rust, fnm, zed installers.
- `install_packages`, `install_package`, `download_tar_bin`, `bin_exists`, `detect_arch`, `ensure_dir` — already used by Linux paths.

No shim extension is required for any phase.

## Verification (end-to-end)

```bash
just lint && just typecheck && just test                             # static + unit + render snapshot
just build-all                                                       # dist/{debian,macos}/{setup.sh,...}
just shellcheck                                                      # bash lints clean
rg -n 'fedora|FEDORA|dnf|DNF' src/ tests/ justfile           # zero hits
just test-vm debian                                                  # debian VM bootstrap end-to-end
just test-vm macos                                                   # macos VM bootstrap end-to-end
```

## Out of scope

- `Postgres` registration into either env (separate decision).
- Adding new GUI-only components to macOS.
- Renaming the repo's "env" terminology now that there are only two.
- Rewriting historical plans `01–06` beyond a one-line "superseded by Plan 07" header.
