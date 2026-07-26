# Plan 15 — Rootless Docker Engine for full Debian

## Context

The full `debian` environment is a development machine but does not currently
install a container engine. The separate `debian-docker` environment is only a
small Docker-built integration target and must not become a Docker host.

Docker officially supports Debian 13 Trixie. Its current installation path uses
Docker's stable apt repository, an armored key at
`/etc/apt/keyrings/docker.asc`, and a deb822 source at
`/etc/apt/sources.list.d/docker.sources`. Rootless mode also requires `uidmap`,
a subordinate UID/GID allocation, a systemd user manager, and
`dockerd-rootless-setuptool.sh` running as the regular user.

The generated setup already rejects root and authenticates sudo before running
components. Preserve that boundary: repository/package/system operations use
sudo; the daemon, user unit, and Docker CLI context belong to the deploying
regular user.

Official references:

- <https://docs.docker.com/engine/install/debian/>
- <https://docs.docker.com/engine/security/rootless/>
- <https://docs.docker.com/engine/security/rootless/tips/>

## Decisions

- Install Docker only in `ENVIRONMENTS["debian"]`; leave macOS and
  `debian-docker` component composition unchanged.
- Require `ID=debian`, `VERSION_ID=13`, and `VERSION_CODENAME=trixie`. Do not
  silently target another Debian release or derivative.
- Use Docker's current deb822 repository format and stable channel. Do not use
  `apt-key`, Debian's `docker.io`, package preferences, or hard-pinned versions.
- Install `docker-ce`, `docker-ce-cli`, `containerd.io`,
  `docker-buildx-plugin`, `docker-compose-plugin`,
  `docker-ce-rootless-extras`, and `uidmap`.
- Remove Docker's documented conflicts with `apt remove`, never `purge`:
  `docker.io`, `docker-compose`, `docker-doc`, `podman-docker`, `containerd`,
  and `runc`. Never delete engine data directories.
- Make rootless mode exclusive. Permanently mask rootful `docker.service` and
  `docker.socket` before installing Docker CE so package post-install scripts
  cannot expose a rootful daemon, including on a partial package failure.
- Never pass `--force` to the rootless setup tool and never add the user to the
  root-equivalent `docker` group.
- Require one validated, contiguous subordinate UID range and one subordinate
  GID range of at least 65,536 IDs for the deploying account. Production setup
  fails rather than allocating a potentially colliding range.
- Enable linger and use logind's canonical `/run/user/<uid>` runtime.
- Persist and prefer the Docker CLI context named `rootless`; do not export
  `DOCKER_HOST` globally.
- Treat cgroup v2 as a project requirement for this Debian 13 development
  machine, without claiming that all controllers are delegated.
- Keep the rootless socket unavailable inside the Pi bubblewrap sandbox.

## Pre-flight and sequencing

The current worktree contains uncommitted Plan 14 vendoring changes that overlap
`src/dotgen/shim.py`, component/shim tests, snapshot logic, and golden output.
Land or otherwise establish a reviewed Plan 14 baseline before Docker snapshot
refresh. Preserve those changes and review Docker deltas separately.

Plan 13's sudo fixture work is independent. It does not provision subordinate
IDs. Before runtime acceptance, verify whether the current OrbStack backend
already satisfies noninteractive sudo; implement Plan 13 separately only if that
precondition still fails. This plan adds its own fixture-only subordinate-ID
preparation because a fresh OrbStack Trixie account currently has no mappings.

Before implementation:

```bash
git status --short
git diff -- src/dotgen/shim.py tests/test_shim.py \
  tests/test_components.py tests/test_render_snapshot.py tests/golden/
```

## Tasks

### 1. Define exact generic shim contracts

Update `src/dotgen/shim.py` and the documented shim contract in `CLAUDE.md`.
Preserve the existing `add_repo apt ...` and `add_repo tap ...` behavior used by
GitHub CLI, PostgreSQL, and macOS.

Add these contracts:

```text
add_repo apt-deb822 <id> <source-content> <armored-key-url>
remove_packages <pkg>...
service_mask <unit>...
```

#### `add_repo apt-deb822`

On Debian:

- Accept a complete deb822 stanza as one argument and normalize it to exactly
  one trailing newline.
- Download the armored key into a private temporary file on every comparison,
  validate that GnuPG can parse it, and clean up temporary files on every path.
- Compare key and source independently with their installed targets.
- In `diff` mode, print separate absent/drift reports without writing.
- In deploy mode, atomically install only changed content as mode `0644` at
  `/etc/apt/keyrings/<id>.asc` and
  `/etc/apt/sources.list.d/<id>.sources`; unchanged files retain their mtimes.
- Reject an invalid `id`, malformed source content, a `Signed-By` path that does
  not match the target key, or an unavailable/invalid key.
- Fail with remediation if same-ID legacy files such as `docker.list` or
  `docker.gpg` already exist. Do not delete administrator-owned repository
  configuration automatically.

On macOS, `apt-deb822` must fail as unsupported. Keep legacy `apt` and `tap`
behavior byte-compatible.

#### `remove_packages`

- On Debian, skip absent packages and invoke one noninteractive
  `apt-get remove -y` for the installed subset.
- In `diff` mode, report only installed packages and make no changes.
- Never purge packages or remove `/var/lib/docker`, `/var/lib/containerd`,
  `~/.local/share/docker`, or Podman storage.
- On macOS, fail as unsupported rather than silently succeeding.

#### `service_mask`

- On Debian deploy, run `systemctl mask --now` through sudo for all requested
  units and verify each unit is masked and inactive.
- In `diff` mode, report units not already masked without mutation.
- On macOS, fail as unsupported.

Add the new function names to `SHIM_FUNCTIONS` and the mode-aware helper set so
all OS shims retain identical function names and side-effect rules.

### 2. Add a full-Debian Docker component

Create `src/dotgen/components/docker.py` as a frozen component named `docker`.
It must defensively apply only to `env.name == "debian"` and return a setup-only
`Fragment`.

Separate the generated setup into explicit preflight, package transition, and
rootless-user phases. Every direct mutation must be skipped in
`DOTGEN_MODE=diff`.

### 3. Run all possible safety checks before Docker package mutation

Before conflict removal or Docker repository/package changes:

- Validate `/etc/os-release` reports Debian 13 Trixie.
- Restrict `dpkg --print-architecture` to Docker-supported project targets
  (`amd64` and `arm64` unless another architecture is deliberately added and
  VM-tested).
- Require systemd, logind, a reachable system manager, and cgroup v2 via
  `/sys/fs/cgroup/cgroup.controllers`.
- Validate the deploying username and numeric UID/GID.
- Install only Debian's `uidmap` prerequisite at this stage, then require
  `newuidmap`, `newgidmap`, and `getsubids`.
- Resolve mappings by username, with numeric UID/GID fallback matching the
  runtime tools. Require one contiguous range with a decimal count of at least
  65,536 in each file.
- Reject malformed/overflowing ranges, a range containing the deploying host
  UID/GID, and overlap with a range assigned to a different principal. Cover the
  accepted username/numeric forms and rejection cases with table-driven tests.
- Inspect setup markers under fixed effective paths:
  `~/.config/systemd/user/docker.service` and the `rootless` context in
  `~/.docker`. Record neither/both/partial state before mutation.

If any check fails, stop before removing conflicting packages or adding Docker's
repository. Installing `uidmap` is the only allowed preflight mutation.

### 4. Prevent package-started rootful Docker

After preflight passes and before removing/installing engine packages:

1. Mask `docker.service` and `docker.socket` with `service_mask`.
2. Verify the standard units are masked and inactive.
3. If `/var/run/docker.sock` exists, do not unlink it automatically. Check for a
   live listener; fail with administrator remediation whether it is live or
   merely stale. A clean fresh host must have no path there.
4. Install Docker's official armored key and this deterministic source via
   `add_repo apt-deb822 docker ...`:

   ```text
   Types: deb
   URIs: https://download.docker.com/linux/debian
   Suites: trixie
   Components: stable
   Architectures: <validated architecture>
   Signed-By: /etc/apt/keyrings/docker.asc
   ```

5. Remove exactly Docker's documented conflicts through `remove_packages`.
6. Refresh apt metadata and install the unpinned CE, CLI, containerd, buildx,
   Compose, and rootless-extras package set through shim helpers.
7. Reassert that the rootful units remain masked/inactive and no rootful socket
   exists before invoking rootless setup.

Keeping the units masked is intentional. It closes the rootful startup window
when apt installs packages one at a time and remains fail-safe if a later package
or rootless configuration step aborts.

The component must contain no `apt-get`, `brew install`, `service_enable docker`,
`--force`, `usermod`, or docker-group mutation.

### 5. Establish one canonical user runtime and config boundary

In deploy mode after package installation:

- Enable linger with `sudo loginctl enable-linger "$(id -un)"`.
- Resolve `RuntimePath` from `loginctl show-user`; require it to equal
  `/run/user/$(id -u)`.
- Reject a caller-provided `XDG_RUNTIME_DIR` when it differs from that canonical
  path, then export the canonical value only inside the component subshell.
- Start `user@<uid>.service` through the system manager when necessary.
- Set component-local `DBUS_SESSION_BUS_ADDRESS` to the bus below the canonical
  runtime path.
- Use a bounded readiness loop for the runtime directory, user bus, and
  `systemctl --user`; on timeout, report `loginctl` and user-unit diagnostics.
- Require the runtime directory to be owned by the deploying UID and not be
  group/world accessible.
- Fix the setup boundary to `XDG_CONFIG_HOME=$HOME/.config` and
  `DOCKER_CONFIG=$HOME/.docker`. Reject or locally override caller values so
  marker inspection, setup, context selection, and verification cannot diverge.
- Locally clear `DOCKER_HOST` and `DOCKER_CONTEXT` for every setup/context/info
  command. Do not persist any of these variables in `.bashrc`.

### 6. Configure rootless Docker with an executable idempotency contract

Use the fixed user-unit and CLI-context markers:

- If neither marker exists, run `dockerd-rootless-setuptool.sh install` exactly
  once as the regular user.
- If both exist, skip the setup tool.
- If only one exists, fail as inconsistent state with manual repair guidance.
- Never use `--force` or overwrite partial state automatically.

For first and repeated deploys:

- enable/start the user `docker.service`;
- select the persisted `rootless` context;
- require its endpoint to be exactly
  `unix:///run/user/<uid>/docker.sock`;
- require the socket to exist and be owned by the deploying UID;
- require `docker info` security options to include `rootless` and its reported
  cgroup version to be `2`;
- recheck that rootful units remain masked/inactive and `/var/run/docker.sock`
  remains absent.

Do not rely on user-unit content or mtime to prove that the setup tool was
skipped: the upstream tool may preserve both even when invoked again.

### 7. Register Docker only in full Debian

Update `src/dotgen/registry.py`:

- import the component;
- define an explicit one-item `_DEBIAN_FULL` tuple;
- compose Debian as `_SHARED + _DEBIAN_FULL + _LAST`;
- leave macOS and `debian-docker` expressions unchanged;
- do not add Docker to `_SHARED` or `_DOCKER_SKIP`.

Docker therefore runs after shared tooling and before `GitSetup` and
`DotfilesDeploy`; the final-deployer ordering invariant remains intact.

### 8. Document host policy and remediation

Update `README.md` to document:

- official stable Docker repository/package installation in full Debian;
- the Debian 13 Trixie requirement;
- how an administrator inspects and allocates non-overlapping subordinate UID
  and GID ranges before production deployment;
- rootful service/socket masking and the absence of docker-group grants;
- linger, the user service, `rootless` context, and verification commands;
- no global `DOCKER_HOST`;
- conflict removal without purge/data deletion;
- no automatic migration from rootful storage to
  `~/.local/share/docker`;
- manual handling for pre-existing Docker repository files, rootful sockets, and
  partial rootless unit/context state.

Preserve Plan 12's private artifact and regular-user/sudo workflow.

### 9. Add focused static and executable tests

Update `tests/test_components.py` for component/applicability/composition facts:

- Docker appears only in full Debian at the intended position.
- The exact official source, key URL, conflicts, and unpinned package set render.
- Forbidden raw package-manager calls, rootful enablement, `--force`, group
  mutation, global `DOCKER_HOST`, and Pi socket exposure are absent.

Update `tests/test_shim.py` with behavioral tests for:

- deb822 absent/drift/unchanged deploy and diff paths;
- key and source independent reporting, temp cleanup, modes, atomic replacement,
  and unchanged mtimes;
- malformed input and same-ID legacy collision failures;
- unchanged legacy apt/tap behavior;
- batched package removal without purge/data deletion;
- service masking, sudo use, diff safety, and cross-OS parity.

Add `tests/test_docker_component.py` as a fake-command/state Bash harness around
the rendered Docker setup. It must execute—not merely search—the control flow and
assert:

- preflight failure occurs before conflict removal/repository/CE installation;
- rootful units are masked before engine packages and remain masked on a
  synthetic package failure;
- no existing rootful socket is unlinked;
- setup-tool invocation count is one for neither-marker state, zero for
  both-marker state, and zero plus failure for each partial-marker state;
- diff mode performs no mutating command or daemon contact;
- username and numeric subordinate-ID records, malformed/short/overflowing and
  overlapping ranges, canonical/conflicting runtime paths, delayed user-bus
  readiness, and timeout diagnostics follow the contract;
- Docker environment overrides cannot redirect context setup or verification.

### 10. Prepare subordinate IDs only in the disposable Debian VM

Fresh OrbStack Trixie guests currently lack `/etc/subuid` and `/etc/subgid`
entries for the backend-returned regular account. Add fixture-only preparation
behind the VM abstraction rather than weakening production setup:

- Extend `src/dotgen/vm.py` with a narrowly named backend/handle operation for
  rootless-container subordinate IDs.
- Implement it for `_OrbBackend` through root transport before bundle deployment.
- Validate the account name/UID, scan existing allocations, select the first
  collision-free 65,536-ID UID and GID ranges within the configured subordinate
  ranges, write them with account-management tooling, and verify the resulting
  entries.
- Keep Docker and Tart implementations explicit no-ops or unsupported paths;
  call the operation only for the full Debian fixture.
- Never apply this fixture administration to generated production bundles.
- Add mocked transport/validation/error/cleanup tests in `tests/test_vm.py`.

Call the preparation in `tests/test_vm_integration.py` before transferring or
running the bundle. Independently require the existing sudo preflight to pass;
if it does not, complete Plan 13 rather than folding passwordless sudo into this
subordinate-ID operation.

### 11. Add Debian runtime acceptance

Extend `tests/test_vm_integration.py` with full-Debian assertions:

- fixture-provisioned subordinate mappings satisfy the production validator;
- rootful units are masked/inactive and `/var/run/docker.sock` is absent;
- `docker context show` is `rootless`;
- the endpoint and live socket are under `/run/user/<uid>`;
- the user service is enabled/active;
- `docker info` reports rootless mode and cgroup v2;
- setup did not add the user to `docker`;
- `docker run --rm hello-world` succeeds;
- Pi's sandbox cannot see the host rootless socket.

After the existing second deploy, reassert the same state. Invocation-count
proof belongs to the executable fake harness, not unit mtime. `just test-vm
debian-docker` and `just test-vm macos` are optional regression evidence because
the Docker component does not render there.

A backend skip, sudo-preflight failure, subordinate-ID preparation failure, or
omitted container run is missing acceptance evidence.

## Snapshot impact

After reconciling Plan 14, refresh with the existing snapshot workflow. Expected
Docker deltas are:

- `tests/golden/debian/setup.sh`: one Docker component section;
- `tests/golden/debian/os_shim.sh`: deb822 plus generic helper changes;
- `tests/golden/debian-docker/os_shim.sh`: the same Debian shim changes only;
- `tests/golden/macos/os_shim.sh`: parity helper definitions only.

No Docker-driven change is expected in macOS or `debian-docker` setup, any
`.bashrc`/`alias.sh`, or any config manifest.

## Critical files

Expected additions/modifications:

- `src/dotgen/components/docker.py`
- `src/dotgen/registry.py`
- `src/dotgen/shim.py`
- `src/dotgen/vm.py`
- `CLAUDE.md`
- `README.md`
- `tests/test_components.py`
- `tests/test_docker_component.py`
- `tests/test_shim.py`
- `tests/test_vm.py`
- `tests/test_vm_integration.py`
- `tests/golden/debian/setup.sh`
- `tests/golden/debian/os_shim.sh`
- `tests/golden/debian-docker/os_shim.sh`
- `tests/golden/macos/os_shim.sh`

Expected unchanged:

- `src/dotgen/render.py`
- `src/dotgen/components/pi_agent.py`
- `tests/test_render_snapshot.py`
- `dist/debian-docker/Dockerfile`
- all `.bashrc`, alias, and config-manifest goldens

## Verification

Run focused checks first:

```bash
uv run pytest tests/test_components.py tests/test_docker_component.py \
  tests/test_shim.py tests/test_vm.py tests/test_setup_dispatcher.py -q
grep -rE 'apt-get|brew install' src/dotgen/components/  # zero hits
uv run ruff check src tests
uv run ty check src
```

After reconciling Plan 14, refresh and inspect generated output:

```bash
UPDATE_GOLDEN=1 just test
git diff -- tests/golden/debian/setup.sh \
  tests/golden/debian/os_shim.sh \
  tests/golden/debian-docker/setup.sh \
  tests/golden/debian-docker/os_shim.sh \
  tests/golden/macos/setup.sh \
  tests/golden/macos/os_shim.sh \
  tests/golden/*/.bashrc \
  tests/golden/*/alias.sh \
  tests/golden/*/config-manifest.txt
```

Run the complete static/generated-Bash gate:

```bash
just ci
grep -q '^# --- docker ---$' dist/debian/setup.sh
! grep -q '^# --- docker ---$' dist/debian-docker/setup.sh
! grep -q '^# --- docker ---$' dist/macos/setup.sh
! grep -q '^export DOCKER_HOST=' dist/debian/.bashrc
```

Run mandatory runtime acceptance:

```bash
just test-vm debian
```

The Debian run must be non-skipped and prove first deployment, container
execution, sandbox socket isolation, and healthy redeployment. Optionally run the
unchanged backend regressions:

```bash
just test-vm debian-docker
just test-vm macos
```

Finally:

```bash
git diff --check
git status --short
```

## Risks and non-goals

- Docker stable moves over time; static tests cannot replace a non-skipped VM run
  against the version resolved during acceptance.
- Production subordinate-ID allocation remains administrator-owned because
  automatic fixed ranges can collide. Only the disposable VM fixture allocates.
- Masking rootful units is deliberately stronger than Docker's documented
  disablement and prevents package post-install startup. Existing rootful
  workloads must be stopped/migrated before deployment.
- Existing engine data is retained but not migrated into rootless storage.
- A pre-existing repository definition, rootful socket, or partial rootless
  setup fails safely and requires manual remediation.
- Rootless operation requires a healthy logind/systemd user manager. Do not fall
  back to a manually launched daemon.
- Cgroup v2 is required, but complete CPU/IO/cpuset delegation is not configured
  or claimed.
- Privileged ports below 1024 are not enabled.
- Pi remains unable to access the Docker socket; changing that boundary needs a
  separate security review.
- Plan 14 overlap must be resolved before broad snapshot regeneration.

## End state

The full Debian bundle installs unpinned Docker CE, containerd, buildx, Compose,
and rootless tooling from Docker's official stable deb822 repository. Rootful
Docker units are masked before package installation and remain inactive.
Conflicting distro packages are removed without purging data. The regular user
has administrator-provisioned subordinate IDs, a canonical lingering systemd
user runtime, a persistent `rootless` context, and an active daemon at
`/run/user/<uid>/docker.sock`. Repeated deployment skips setup-tool installation
and revalidates the secured state. No docker-group grant, global `DOCKER_HOST`,
or Pi sandbox socket exposure is introduced, and macOS plus `debian-docker`
remain unchanged as Docker hosts.
