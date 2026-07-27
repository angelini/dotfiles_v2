# Plan 17 — Package Stinkpot as the persistent Bash history backend

## Goal

Cross-build a pinned Stinkpot revision on the machine producing the dotgen
bundle, include the appropriate executable artifacts in each environment
tarball, migrate `~/.bash_history` once on deployment, and use Stinkpot for
cross-session persistence and `Ctrl-R` search.

Supported packaged targets are deliberately limited to:

- Linux amd64;
- Linux arm64;
- Darwin arm64.

Darwin amd64 is unsupported and must not be built, packaged, or silently fall
back to another artifact. Its explicit rejection remains covered by tests.

Bash must retain only the in-memory history required by Stinkpot's upstream
prompt hook. When Stinkpot is available, Bash must stop writing a parallel
persistent history file.

## Context and upstream assessment

The assessed upstream is <https://tangled.org/oppi.li/stinkpot> at commit
`cdf87ffcd36e96f3d49316d57fa17cc6ea8371df`.

Relevant behavior at that revision:

- `eval "$(stinkpot init)"` installs an idempotent `PROMPT_COMMAND` recorder and
  binds `Ctrl-R` through Bash `bind -x`.
- `stinkpot import --file <path>` imports an existing Bash history file.
- History is stored in `${XDG_DATA_HOME:-$HOME/.local/share}/stinkpot/history.db`.
- SQLite uses WAL mode, a five-second busy timeout, and one unique row per
  command. Repeating a command replaces its cwd, exit status, timestamp, and
  session rather than preserving a separate event.
- Search considers the newest 10,000 unique commands.
- There is no configurable retention, ignore/redaction rule, sync, export
  command, or schema-migration framework.
- The source declares Go `1.26.4` and uses a pure-Go SQLite implementation.
- The upstream Nix flake includes Linux and Darwin on amd64 and arm64 with
  `CGO_ENABLED=0`.

Local pre-flight builds with `CGO_ENABLED=0` succeeded for Linux amd64, Linux
arm64, Darwin amd64, and Darwin arm64. Plan 17 intentionally drops Darwin amd64
despite that technical capability. The generated init script passed `bash -n`.
A local Darwin arm64 smoke test observed approximately 7.6 ms per
`stinkpot add` process; treat that as feasibility evidence rather than a
performance guarantee.

The pinned source archive is:

```text
https://tangled.org/oppi.li/stinkpot/archive/cdf87ffcd36e96f3d49316d57fa17cc6ea8371df?format=tar.gz
```

Its observed SHA-256 is:

```text
3482ea0c2e729de6e24067d97e91eb969cde2c3a3d9610ca2f0f745b2b20ef32
```

Upstream currently has four commits, no tags, no release binaries, no automated
tests or CI, and no license file. The user approved private deploy-host builds
and inclusion of their outputs in bundles sent to machines under the user's
control. Do not commit generated Stinkpot binaries to this repository or publish
the resulting bundles. A license or explicit upstream permission remains a gate
for broader redistribution.

The current persistent-history policy is entirely in
`src/dotgen/components/bash_base.py` and is emitted identically for `debian`,
`debian-docker`, and `macos`:

```bash
HISTSIZE=1000000
HISTFILESIZE=1000000
HISTCONTROL=ignoredups:erasedups
shopt -s histappend
PROMPT_COMMAND="history -a;set_win_title;${PROMPT_COMMAND:-}"
```

The project environment model records OS but not destination architecture.
Generic bundles therefore need every supported architecture for their OS:
Linux tarballs carry amd64 and arm64; the macOS tarball carries arm64 only.
`setup.sh` selects exactly one artifact using runtime OS/architecture detection.

`debian-docker` currently excludes `GoLang`. Cross-building before transfer
preserves that smaller destination environment: no Go compiler, source archive,
Go module cache, or network source build is required on any destination host.
The existing target-side `GoLang` version and registry order remain unchanged.

The Pi sandbox deliberately hides `~/.bash_history`, but currently exposes
`~/.local/share`. Replacing Bash history without hiding
`~/.local/share/stinkpot` would regress that security boundary.

## Scope

- Add a declarative generated-binary artifact type to fragments and rendering.
- Fetch and checksum the pinned source on the bundle-producing host.
- Cross-build Linux amd64, Linux arm64, and Darwin arm64 with Go `1.26.4` and
  `CGO_ENABLED=0`.
- Package both Linux binaries in `debian` and `debian-docker`; package only the
  Darwin arm64 binary in `macos`.
- Add one dedicated `Stinkpot` component to all three environments.
- Select, verify, and atomically install the matching bundled binary as
  `$HOME/bin/stinkpot` without destination-side compilation or downloads.
- Import a pre-existing `~/.bash_history` exactly once before replacing the
  generated `.bashrc`.
- Preserve the legacy history file unchanged as a rollback artifact.
- Remove the existing `HISTSIZE`, `HISTFILESIZE`, `HISTCONTROL`, `histappend`,
  and `history -a` policy.
- Preserve window-title updates and pre-existing `PROMPT_COMMAND` behavior with
  idempotent recorder-first ordering.
- Hide Stinkpot's data directory from Linux and macOS Pi sandboxes.
- Add artifact-builder, component, shell-policy, sandbox, snapshot, package, and
  VM coverage.
- Document storage, privacy, migration, unsupported Darwin amd64, build-host
  requirements, and upstream maturity/license constraints.

## Out of scope

- Darwin amd64 support or a universal Darwin binary.
- Building Stinkpot on destination hosts.
- Installing Go in `debian-docker` or moving/upgrading the target-side
  `GoLang` component for Stinkpot.
- Committing generated executables, source archives, or Go caches.
- Publishing bundles containing Stinkpot while upstream has no license.
- Forking or patching Stinkpot.
- Zsh/fish integration, history synchronization, encryption, secret redaction,
  retention controls, or command ignore patterns.
- Preserving every repeated command event; upstream stores unique command text.
- Automatically deleting, renaming, truncating, or exporting
  `~/.bash_history` or the Stinkpot database.
- Recovering post-migration Stinkpot-only history into Bash format; upstream has
  no exporter.
- Automatically adopting a newer commit. Every upgrade requires a source,
  dependency, schema, and security review plus a new checksum.

## Pre-flight and sequencing

The working tree already contains unrelated Docker/Plan 15 changes, including
overlaps in `README.md`, `tests/test_components.py`, and
`tests/golden/debian/setup.sh`. Preserve that work and review Plan 17 deltas
separately.

Before implementation:

```bash
git status --short
git diff -- README.md src/dotgen/fragment.py src/dotgen/render.py \
  src/dotgen/registry.py src/dotgen/components/bash_base.py \
  src/dotgen/components/pi_agent.py tests/test_components.py \
  tests/test_render_snapshot.py tests/test_vm_integration.py tests/golden/
```

The bundle-producing host must have a Go launcher new enough to support toolchain
selection. Production artifact generation pins `GOTOOLCHAIN=go1.26.4+auto`,
checks that the effective compiler reports exactly `go1.26.4`, and fails with a
clear remediation message rather than building with another version.
Destination hosts have no Go requirement. A cold build host may download the
pinned Go toolchain and module dependencies; those downloads occur only on the
bundle-producing host.

Artifact generation must fail closed if the source archive no longer matches
the recorded SHA-256. Do not switch to `main`, a tag, a mirror, an upstream
binary, or `go install ...@latest`.

## Steps

### 1. Add declarative generated-binary artifacts

Extend `src/dotgen/fragment.py` with a frozen binary-build declaration rather
than executing network or compiler work from `Component.render()`. The
contract must carry enough immutable data to reproduce and audit a build:

- logical artifact name;
- destination path inside the generated environment;
- source URL and SHA-256;
- required Go version;
- target `GOOS` and `GOARCH`;
- source subdirectory if needed;
- build flags and output mode.

Add an `artifacts` tuple to `Fragment` and merge it like `configs` and
`vendors`, rejecting duplicate destination paths. Keep component rendering pure:
unit tests that call `Stinkpot.render()` must not download or compile anything.

Create a focused build module such as `src/dotgen/artifact.py` and have
`render.build_env()` materialize declared artifacts after fragments are merged.
The production builder must:

1. Accept only the declared HTTPS source and exact SHA-256.
2. Download the source once per build invocation, even when `build-all` renders
   both Debian environments.
3. Verify SHA-256 before extraction.
4. Reject archive members with absolute paths, `..` traversal, or unexpected
   links before extracting into a private temporary directory.
5. Verify `go.mod`, `go.sum`, and `main.go` are regular files.
6. verify the effective compiler reports exactly `go1.26.4`;
7. build with `CGO_ENABLED=0`, explicit `GOOS`/`GOARCH`,
   `GOTOOLCHAIN=go1.26.4+auto`, `-trimpath`, `-buildvcs=false`, and stripped
   linker flags;
8. use build-host-only `GOMODCACHE`/`GOCACHE` locations outside `dist/`;
9. write each output atomically as mode `0755` under the requested environment;
10. emit a deterministic `SHA256SUMS` beside the built artifacts;
11. clean private source/build staging on success, error, and handled signals.

Use one shared in-process build cache for `build_all()` so Linux targets compile
once and are copied into both `debian` and `debian-docker`. A single-environment
build compiles only the targets declared by that environment.

Production CLI/build paths use the real builder. Every ordinary test that calls
`build_env()` injects a deterministic fake builder so `just test` performs no
network or Go compilation. VM integration and `just build[-all]` exercise the
real builder. Do not make a missing pre-generated binary in the repository a
hidden prerequisite.

### 2. Declare the supported Stinkpot artifact matrix

Create `src/dotgen/components/stinkpot.py` with one frozen `Stinkpot` dataclass.
It applies to all three environments and declares artifacts by OS:

```text
debian         artifacts/stinkpot/linux-amd64/stinkpot
               artifacts/stinkpot/linux-arm64/stinkpot
debian-docker  artifacts/stinkpot/linux-amd64/stinkpot
               artifacts/stinkpot/linux-arm64/stinkpot
macos          artifacts/stinkpot/darwin-arm64/stinkpot
```

Do not declare `darwin-amd64`, `x86_64-darwin`, or a universal binary anywhere.
Use the same source pin, checksum, Go version, and build flags for every target.
The artifact declaration, not conditionals in `render.build_env()`, is the
source of truth for the matrix.

Register `Stinkpot()` in `_SHARED` after `CoreUtils()` and before consumers that
do not affect it. Preserve the current `GoLang()` position and keep `go_lang` in
`_DOCKER_SKIP`; destination setup no longer depends on Go.

### 3. Install the matching bundled binary

The Stinkpot setup contribution must select an artifact using `detect_os` and
`detect_arch`:

- Debian/Linux `x86_64` → `linux-amd64`;
- Debian/Linux `aarch64|arm64` → `linux-arm64`;
- macOS `arm64|aarch64` → `darwin-arm64`;
- macOS `x86_64` and every other combination → clear unsupported-target error.

Do not fall back from Darwin amd64 to an ARM binary, source build, Rosetta, a
package manager, or network download.

Before installation:

- require the selected source to be a regular, non-symlink, executable file;
- verify its SHA-256 against the generated `SHA256SUMS` with `sha256sum` on
  Debian and `shasum -a 256` on macOS;
- reject a malformed manifest, duplicate entry, checksum mismatch, or missing
  artifact.

In `diff` mode, compare the selected bundle artifact with
`$HOME/bin/stinkpot` and report only install/change metadata. Perform no write.
In deploy mode, stage mode `0755` in `$HOME/bin` and use same-directory `mv` for
atomic replacement. Skip an already byte-identical executable so redeploy
preserves its mtime. No install-version marker is needed because the bundled
binary itself is the exact desired state.

### 4. Migrate and secure legacy Bash history exactly once

After a valid binary is installed and before `DotfilesDeploy` replaces
`.bashrc`, use a migration marker at:

```text
${XDG_STATE_HOME:-$HOME/.local/state}/dotgen/stinkpot/bash-history-import-v1
```

When the marker is absent:

- reject a symlink or non-directory at the Stinkpot data-directory path;
- initialize the data directory and schema under `umask 077`, even when no
  legacy file exists, so the directory is mode `0700` and the database begins
  mode `0600`;
- if `$HOME/.bash_history` is a non-empty regular file, run
  `stinkpot import --file "$HOME/.bash_history"` under the same private umask;
- if the file is absent or empty, treat migration as a successful no-op;
- atomically create the migration marker mode `0600` only after successful
  initialization and import/no-op;
- preserve the original history file byte-for-byte;
- in `diff` mode, report pending migration without touching data or state.

Never rerun import after the marker exists. Importing timestamp-less Bash
history again would refresh duplicate timestamps and distort Stinkpot ordering.
Do not infer migration completion merely from database existence because the
user may already have tested Stinkpot manually.

A failed install or import must prevent `DotfilesDeploy` from replacing
`.bashrc`, leave the migration marker absent, and preserve any existing working
binary/database as far as the failed operation allows.

### 5. Replace Bash's persistent-history policy

Change `src/dotgen/components/bash_base.py` to remove:

- `HISTSIZE=1000000`;
- `HISTFILESIZE=1000000`;
- `HISTCONTROL=ignoredups:erasedups`;
- `shopt -s histappend`;
- `history -a` in `PROMPT_COMMAND`.

Keep `set_win_title`, but register it idempotently. Re-sourcing `.bashrc` must
not duplicate the title hook or move the Stinkpot recorder away from the first
position.

Add Stinkpot's Bash contribution after BashBase's title-hook contribution:

```bash
if bin_exists stinkpot; then
  export HISTFILE=/dev/null
  eval "$(stinkpot init)"
else
  printf 'warning: stinkpot is unavailable; using Bash history defaults\n' >&2
fi
```

Equivalent project-style wording is acceptable, but preserve these semantics:

- redirect Bash persistence only after confirming the executable exists;
- do not restore the removed history tuning in the fallback path;
- preserve scalar `PROMPT_COMMAND` content that existed before generated code;
- after first or repeated sourcing, `__stinkpot_record` is first and
  `set_win_title` occurs once;
- let upstream own the recorder and `Ctrl-R` binding.

Do not add `ignorespace`: upstream reads `history 1`, so a command Bash omits can
cause the previous command to be recorded again. Document that Stinkpot stores
plaintext commands and has no per-command opt-out.

### 6. Preserve the Pi history boundary

Add `.local/share/stinkpot` to `SANDBOX_HOME_POLICY.hidden_dirs` in
`src/dotgen/components/pi_agent.py`. The nested deny must override the broader
writable `.local/share` mount on Linux and in the macOS seatbelt profile.

Tests must prove:

- the path is in `hidden_dirs`, not `hidden_files`;
- bubblewrap emits a nested tmpfs mount;
- seatbelt denies it as a subpath;
- unrelated writable `.local/share` state remains available;
- full Debian and macOS `pi-sandbox` cannot read or modify the database.

Do not hide all of `.local/share`. Existing VM policy skips Pi sandbox execution
inside `debian-docker` because that container cannot create the required
unprivileged user namespace; cover its generated policy without weakening the
runtime sandbox.

### 7. Add focused artifact and component tests

Add or extend tests for these contracts:

#### Artifact declarations and builder

- Linux environments declare exactly amd64 and arm64.
- macOS declares exactly Darwin arm64.
- No declaration or output path contains Darwin amd64.
- Source URL, source SHA-256, Go version, target tuple, flags, destination, and
  mode are exact.
- Duplicate destinations fail during fragment merge.
- Fake-builder snapshot paths perform no network or compiler calls.
- Real-builder command construction sets the declared target and `CGO_ENABLED=0`.
- Compiler-version, download, checksum, archive-validation, extraction,
  dependency-download, and compile failures leave no partial artifact.
- `build_all()` builds each unique target once while packaging Linux outputs in
  both Linux environments.
- `SHA256SUMS` is sorted, unique, and matches generated bytes.
- Generated executables are mode `0755`; no source or Go cache appears in the
  environment output.

Use local fixture archives and fake `curl`/Go processes for ordinary tests.
Unit tests must not contact Tangled, Go proxies, or `go.dev`.

#### Installation and migration

- Runtime mapping accepts Linux `x86_64`, Linux `aarch64|arm64`, and Darwin
  `arm64|aarch64` only.
- Darwin `x86_64` fails before installing anything.
- Diff mode is read-only.
- Missing, symlinked, malformed, or checksum-mismatched bundle artifacts fail.
- Deploy atomically installs mode `0755`; identical redeploy preserves mtime.
- Legacy history imports once, remains unchanged, and records completion only
  after success.
- Absent/empty legacy history initializes secure state without invoking import.
- `CoreUtils < Stinkpot < DotfilesDeploy` in every environment.
- `GoLang` and `_DOCKER_SKIP` remain unchanged by Plan 17.

#### Generated Bash behavior

Assert generated Bash contains none of `HISTSIZE`, `HISTFILESIZE`,
`HISTCONTROL`, `histappend`, or `history -a`, and gates
`HISTFILE=/dev/null` on Stinkpot availability.

Source generated `.bashrc` twice with a fake `stinkpot init` and prove:

- one recorder hook and one title hook;
- recorder-before-title ordering;
- preservation of a pre-existing scalar prompt hook;
- the command exit status reaches the recorder;
- `Ctrl-R` still resolves to one `__stinkpot_search` action;
- missing Stinkpot does not redirect `HISTFILE`.

### 8. Add package and runtime acceptance

Extend `tests/test_vm_integration.py` for `debian`, `debian-docker`, and
Darwin arm64 `macos`. Prove:

- the pushed tarball already contains the expected target binary;
- deployment performs no Stinkpot source download or compilation;
- `stinkpot` resolves and starts from a login shell;
- the installed binary equals the selected bundled artifact;
- `HISTFILE=/dev/null` when Stinkpot is available;
- a unique command recorded from one Bash process appears from another with its
  exit status;
- concurrent `stinkpot add` processes avoid locked-database failures;
- the data directory is mode `0700` and database starts mode `0600`;
- redeploy preserves the database, binary mtime, and migration marker;
- a seeded legacy command imports once and its source file remains unchanged;
- full Debian and macOS Pi sandboxes cannot read the database.

Add a focused unsupported-target harness for Darwin amd64 rather than adding an
Intel macOS VM. It must prove setup fails with a clear message and does not try
another artifact or build path.

### 9. Refresh generated expectations and documentation

Regenerate snapshots only after focused tests pass.

Expected `setup.sh` changes:

- every environment gains bundled-artifact selection, verification,
  installation, and one-time migration;
- Linux setup supports amd64 and arm64;
- macOS setup supports arm64 only and explicitly rejects x86_64;
- no setup chunk downloads Stinkpot source, invokes Go, or changes `GoLang`.

Expected `.bashrc` changes:

- removal of the current million-entry/native persistence settings;
- idempotent title-hook composition;
- conditional Stinkpot initialization and `HISTFILE=/dev/null`.

Expected generated-artifact changes:

- `debian` and `debian-docker` each contain Linux amd64 and arm64 binaries plus
  `SHA256SUMS`;
- `macos` contains only Darwin arm64 plus `SHA256SUMS`;
- no environment contains source, a Go cache, or a Darwin amd64 binary.

Expected config-manifest changes are limited to generated Pi sandbox hashes.
`alias.sh` and `os_shim.sh` should remain byte-identical. Binary artifacts are
validated behaviorally and through their generated checksum manifest, not
stored as golden files or committed to Git.

Update `README.md` with:

- the pinned upstream revision and deploy-host cross-build model;
- the exact supported target matrix and explicit Darwin amd64 exclusion;
- the Go toolchain-selection requirement and pinned effective Go `1.26.4`;
- binary locations inside bundles and on targets;
- database and migration-marker locations;
- one-time migration and preservation of the legacy file;
- unique-command semantics and 10,000-command search window;
- plaintext/WAL privacy implications and lack of ignore/redaction controls;
- no sync, exporter, or automatic schema recovery;
- rollback limits for post-migration SQLite-only commands;
- no publication or broader redistribution while upstream has no license.

Do not advise deleting the database automatically. Once Bash persistence is
disabled, upstream's suggested delete-and-reimport recovery would lose newer
history.

## Data and control flow

`Stinkpot.render()` declares immutable target artifacts without side effects.
The production render path downloads and verifies one source archive on the
bundle-producing host, compiles each unique declared target once, writes the
artifacts and checksum manifests into environment output, and then normal
packaging includes them in `dist/<env>.tar.gz`.

`just deploy <env> <target>` therefore builds before SCP as it does today. The
tarball sent over the wire already contains every supported architecture for
that environment's OS. Destination `setup.sh` maps runtime architecture to one
artifact, verifies it, atomically installs it, initializes/imports history, and
later `DotfilesDeploy` installs `.bashrc`.

At interactive-shell startup, Stinkpot redirects Bash persistence to
`/dev/null`, prepends `__stinkpot_record`, and binds `Ctrl-R`. The recorder reads
Bash's in-memory `history 1` and writes SQLite. The Pi sandbox overlays only
`.local/share/stinkpot` as hidden while preserving other `.local/share` state.

## Critical files

- `plans/17-stinkpot-shell-history.md`
- `src/dotgen/fragment.py`
- `src/dotgen/artifact.py` (new)
- `src/dotgen/render.py`
- `src/dotgen/components/stinkpot.py` (new)
- `src/dotgen/components/bash_base.py`
- `src/dotgen/components/pi_agent.py`
- `src/dotgen/registry.py`
- `tests/test_artifact.py` (new)
- `tests/test_components.py`
- `tests/test_stinkpot_component.py` (new if not kept with component tests)
- `tests/test_render_snapshot.py`
- `tests/test_vm_integration.py`
- `tests/golden/{debian,debian-docker,macos}/{setup.sh,.bashrc,config-manifest.txt}`
- `README.md`

`src/dotgen/components/go_lang.py`, `src/dotgen/shim.py`,
`tests/test_shim.py`, and `tests/golden/*/os_shim.sh` should not change.

## Verification

Focused tests before golden refresh:

```bash
uv run pytest tests/test_artifact.py tests/test_components.py \
  tests/test_stinkpot_component.py -v
uv run pytest tests/test_vm_integration.py --collect-only -q
uv run ruff check src tests
uv run ty check src
```

If Stinkpot tests remain in `tests/test_components.py`, omit the split test path.

Refresh and inspect snapshots using the deterministic fake artifact builder:

```bash
UPDATE_GOLDEN=1 uv run pytest tests/test_render_snapshot.py -v
git diff -- tests/golden/*/setup.sh tests/golden/*/.bashrc \
  tests/golden/*/config-manifest.txt tests/golden/*/alias.sh \
  tests/golden/*/os_shim.sh
```

Build real artifacts and inspect target matrices:

```bash
just build-all
tar -tzf dist/debian.tar.gz | rg 'artifacts/stinkpot'
tar -tzf dist/debian-docker.tar.gz | rg 'artifacts/stinkpot'
tar -tzf dist/macos.tar.gz | rg 'artifacts/stinkpot'
```

Expected matrix:

```text
debian:        linux-amd64, linux-arm64
debian-docker: linux-amd64, linux-arm64
macos:         darwin-arm64
```

These checks must return no matches:

```bash
find dist -type f \( -path '*darwin-amd64*' -o -path '*x86_64-darwin*' \) -print
rg -n 'HISTSIZE|HISTFILESIZE|HISTCONTROL|histappend|history -a' \
  src/dotgen/components tests/golden/*/.bashrc
rg -n 'stinkpot.*(curl|go build)|go build.*stinkpot' tests/golden/*/setup.sh
```

Inspect package modes and checksums:

```bash
tar -tvzf dist/debian.tar.gz | rg 'artifacts/stinkpot/.*/stinkpot$'
tar -tvzf dist/macos.tar.gz | rg 'artifacts/stinkpot/.*/stinkpot$'
```

Full gate:

```bash
just ci
git diff --check
git status --short
```

Runtime acceptance:

```bash
just test-vm debian
just test-vm debian-docker
just test-vm macos
```

## Decisions

- **Cross-build before transfer.** Pure-Go cross-compilation is proven for the
  selected targets and removes compiler/network work from destinations.
- **Package both Linux architectures.** Environment selection has no destination
  architecture, so generic Linux bundles remain portable across amd64 and arm64.
- **Package only Darwin arm64.** Darwin amd64 is explicitly dropped even though
  upstream can compile for it.
- **Keep target Go unchanged.** The build host selects effective Go `1.26.4`;
  Stinkpot does not alter `GoLang` or add Go to `debian-docker`.
- **Use immutable artifact declarations.** Component rendering remains pure,
  while one audited builder owns downloads, checksums, compilation, caching, and
  output modes.
- **Use the exact commit, not `main`.** Upstream has no releases or compatibility
  policy.
- **Use Stinkpot as the only persistent history store.** Bash retains in-memory
  history because upstream reads `history 1`, but its history file is redirected
  only after Stinkpot availability is confirmed.
- **Import once and preserve the source.** Timestamp-less import is not safely
  repeatable, and preserving the old file improves rollback.
- **Accept unique-command semantics.** This resembles the current
  `ignoredups:erasedups` intent but is not event history.
- **Preserve the Pi history boundary.** The new storage path receives the same
  protection as the old history file.
- **Treat bundles as private artifacts.** Upstream's missing license remains a
  constraint against committing binaries or broader distribution.

## Risks and constraints

- Upstream is new, unlicensed, untagged, and untested. Packaging its binary is
  accepted only for the private deployment scope described above.
- `just build`, `just build-all`, `just deploy`, and `just ci` now require a Go
  launcher capable of selecting `go1.26.4` plus source/toolchain/module network
  access on a cold build host.
- Bundles grow by two Linux binaries or one Darwin binary. Linux source is built
  once per invocation but included in both Linux tarballs.
- There is no exporter. Rollback cannot automatically merge newer SQLite-only
  commands into `.bash_history`.
- There is no schema migration. Never automatically delete/reimport the database
  after Bash persistence becomes stale.
- Commands and metadata are plaintext, including SQLite WAL files. Directory
  permissions and Pi denial reduce exposure but do not provide encryption or
  redaction.
- The init hook launches a process and opens SQLite at every prompt. Local
  latency was acceptable but varies by host.
- `HISTFILE=/dev/null` is set from `.bashrc`, after an initial shell may already
  have read legacy history. It prevents future writes and is inherited by child
  shells.
- The forge's generated archive must remain byte-stable for the pinned checksum.
  A mismatch is a deliberate maintenance failure.
- Darwin amd64 deployment fails by design and requires a future explicit plan if
  support is restored.

## End state

The bundle-producing host verifies one pinned Stinkpot source archive and uses
Go `1.26.4` to build Linux amd64, Linux arm64, and Darwin arm64 artifacts.
Linux tarballs carry both Linux executables; the macOS tarball carries only
Darwin arm64. Darwin amd64 is absent and rejected.

Destination setup selects and verifies the matching bundled executable,
installs it atomically without source/network/compiler work, imports legacy Bash
history once, and initializes Stinkpot in interactive shells. `Ctrl-R` searches
SQLite across sessions, the recorder runs before title/third-party prompt hooks,
and Bash no longer appends commands to `~/.bash_history` while Stinkpot is
available.

The original history file and Stinkpot database remain user-owned and survive
redeployments. Pi cannot access either the old Bash history file or the new
Stinkpot database. Tests cover artifact generation, exact target matrices,
Darwin amd64 rejection, package contents, migration, prompt composition,
concurrency, redeployment, and sandbox isolation.
