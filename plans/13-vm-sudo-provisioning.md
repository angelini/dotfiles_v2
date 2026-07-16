# Plan 13 — Noninteractive sudo provisioning for VM tests

## Context

Plan 12 intentionally made every generated `setup.sh deploy` run as a regular
user, require sudo, and authenticate up front with `sudo -v`. The generated
behavior is correct for real machines, where deployment is interactive.

The opt-in VM suite runs deployment through noninteractive transports. Fresh
Debian OrbStack and macOS Tart guests therefore stop at `sudo -v` before any
assertions run:

```text
sudo: a terminal is required to read the password
[ERROR] unable to authenticate with sudo
```

`debian-docker` already passes because its generated test image grants `alex`
passwordless sudo. The missing behavior belongs in ephemeral VM provisioning,
not in generated production bundles.

The failing `just test-vm-all` run produced 22 fixture errors from two shared
setup failures: all 11 Debian tests and all 11 macOS tests. Debian Docker
completed its applicable tests.

## Decisions

- Keep `src/dotgen/render.py`'s root rejection, sudo requirement, and `sudo -v`
  preflight unchanged.
- Provision passwordless sudo only inside ephemeral integration-test guests.
  The rule disappears when the VM is deleted and is retained only when
  `KEEP_VM=1` is intentionally used for debugging.
- Put backend-specific privilege setup behind the existing `_VmBackend` and
  `VmHandle` boundary. The fixture must not know OrbStack root transport or the
  Tart test-image password.
- Grant sudo only to the backend-returned regular user, using a dedicated
  `/etc/sudoers.d/dotgen-test` file with mode `0440`.
- Validate the drop-in with `visudo`, invalidate cached authentication, and
  require `sudo -n true` before starting deployment.
- Treat Docker preparation as an explicit no-op; its image is already prepared
  by `DOCKERFILE_TEMPLATE`, and the common `sudo -n` postcondition still proves
  that contract.
- Do not change generated files, golden snapshots, production sudo policy, VM
  image references, or component/shim behavior.

## Pre-flight

The installed tools and current guest images were probed before writing this
plan:

- OrbStack 2.2.1 supports `orb -m <machine> -u root ...`.
- A fresh `debian:trixie` guest includes `/etc/sudoers.d`, includes that directory
  from `/etc/sudoers`, provides `/usr/sbin/visudo`, and accepts a validated
  mode-`0440` drop-in. A new regular-user command then passes `sudo -n true`.
- Tart 2.32.1 is installed with the pinned Sequoia image cached.
- The pinned macOS guest provides `/etc/sudoers.d` and `/usr/sbin/visudo`, includes
  `/private/etc/sudoers.d` from `/etc/sudoers`, and accepts authenticated sudo
  from the existing `admin`/`admin` fixture credential.
- `just ci` is green before this change. The failing runtime baseline is
  `9 passed, 2 skipped, 22 errors` from `just test-vm-all`.

Before implementation, confirm the working tree is clean and no stale
`dotgen-test-*` guests are running:

```bash
git status --short
orb list  | grep dotgen-test- || true
tart list | grep dotgen-test- || true
```

## Tasks

### 1. Add a fixture sudo-preparation contract to the VM abstraction

Update `src/dotgen/vm.py`:

- Extend `_VmBackend` with a narrowly named operation such as
  `prepare_deploy_sudo(vm_name, user)`.
- Expose one matching `VmHandle.prepare_deploy_sudo()` method so callers never
  access the private backend object or branch on environment names.
- Have the backend operation return captured command results to the handle, or
  otherwise normalize failures through `VmCommandError` with stdout/stderr.
- Use a fixed logical command label for preparation errors. Never include the
  Tart sudo password or password-bearing shell text in diagnostics.
- After backend preparation, run `sudo -k && sudo -n true` through the normal
  handle transport. This prevents a cached timestamp from masking an invalid or
  ignored sudoers drop-in.

The operation is test-harness administration. Generated deployment still runs
as the regular `VmHandle.user`.

### 2. Provision the Debian OrbStack guest through root transport

Update `_OrbBackend` in `src/dotgen/vm.py`:

- Run one preparation command as guest root with
  `orb -m <vm> -u root sh -c ...`.
- Write `<actual user> ALL=(ALL) NOPASSWD:ALL` to a root-owned temporary file
  outside the active include directory, set mode `0440`, and run `visudo -cf`
  against that staged file.
- Atomically install the validated file as `/etc/sudoers.d/dotgen-test`, and
  remove the staged file on every failure path. Never activate unvalidated
  sudoers content.
- Pass the user as a positional argument or stdin data to a fixed shell program;
  do not interpolate it into shell source.
- Validate the backend-returned account name conservatively before emitting a
  sudoers principal, and fail before privileged mutation if it is malformed.
- Preserve normal Orb commands and deployment under the regular host-derived
  guest user.

Do not ask for or capture the developer's macOS password.

### 3. Provision the macOS Tart guest with its fixture credential

Update `_TartBackend` in `src/dotgen/vm.py`:

- Reuse the existing SSH connection details and `admin` fixture account after
  `_wait_for_ssh()` succeeds.
- Run one `sudo -S -p ''` preparation command and provide the sudo password via
  subprocess stdin, not inside the remote command or logical error text.
- Stage the rule in a root-owned mode-`0440` temporary file outside the active
  include directory, validate it with `/usr/sbin/visudo -cf`, and only then
  atomically install it as `/etc/sudoers.d/dotgen-test`. Remove the staged file
  on every failure path.
- Reuse or extract a small SSH argv helper rather than duplicating transport
  options, while preserving current timeout, output capture, image-cache, and
  teardown behavior.
- Leave the pinned source image untouched; only the disposable clone is
  modified.

The existing SSH transport already uses the public test-image credential. This
change must not copy that credential into generated artifacts or exception
messages.

### 4. Keep Debian Docker behavior stable

Update `_DockerBackend` in `src/dotgen/vm.py` to satisfy the new protocol without
additional guest mutation.

`DOCKERFILE_TEMPLATE` already installs sudo and grants `alex` NOPASSWD access.
The common `sudo -k && sudo -n true` check should still run, making Docker a
regression control rather than silently bypassing the new invariant.

### 5. Prepare sudo before VM deployment

Update the fixture in `tests/test_vm_integration.py`:

- Call `handle.prepare_deploy_sudo()` exactly once immediately after
  `vm_session(...)` yields.
- Perform preparation before bundle transfer, secrets installation, and
  `_deploy_cmd()` so failure cannot leave a partially deployed guest.
- Keep the existing environment matrix, fresh `build_env()` output, macOS
  Homebrew prefix, timeouts, skip-on-unavailable behavior, assertions,
  idempotency rerun, and context-managed teardown unchanged.

### 6. Add focused VM backend tests

Expand `tests/test_vm.py` using the existing subprocess-mocking style:

- Orb preparation uses root only for fixture administration, targets the actual
  regular user, validates a staged mode-`0440` rule before atomic installation,
  and then checks noninteractive sudo as the regular user.
- Unsafe account data is rejected rather than interpolated into shell or
  sudoers syntax.
- Tart preparation sends the sudo password through stdin, not the remote command
  or `VmCommandError`, and checks noninteractive sudo in a separate command.
- Docker preparation introduces no extra privileged setup command while still
  passing the common noninteractive-sudo postcondition.
- A nonzero preparation command retains stdout/stderr in `VmCommandError` and
  still triggers VM teardown.
- Existing binary-safe Orb push behavior remains covered.

Keep `tests/test_setup_dispatcher.py` unchanged. Its root and missing-sudo tests
protect the production behavior that this fixture must satisfy rather than
bypass.

## Critical files

Modified:

- `src/dotgen/vm.py` — backend preparation contract, Orb/Tart implementations,
  Docker no-op, public handle method, and noninteractive postcondition.
- `tests/test_vm.py` — transport, credential-handling, error, and cleanup tests.
- `tests/test_vm_integration.py` — one preparation call before deployment.

Expected unchanged:

- `src/dotgen/render.py`
- `src/dotgen/shim.py`
- `tests/test_setup_dispatcher.py`
- `tests/golden/`
- `dist/`
- `justfile`

## Verification

Run focused static tests first:

```bash
uv run pytest tests/test_vm.py \
  tests/test_setup_dispatcher.py -v
uv run ruff check src tests
uv run ty check src
```

Confirm generated production output did not change:

```bash
just build-all
git diff -- src/dotgen/render.py src/dotgen/shim.py tests/golden dist
```

Run each backend independently so failures identify the transport involved:

```bash
just test-vm debian
just test-vm debian-docker
just test-vm macos
```

Then run both complete validation layers:

```bash
just ci
just test-vm-all
```

Acceptance requires non-skipped runtime proof for all three environments. The
expected integration result is 30 passes and three intentional skips:
`full_addons` on `debian-docker`, plus macOS-only Ghostty on `debian` and
`debian-docker`, with no fixture errors. A backend-unavailable skip must be
reported as missing evidence, not as success.

Finally verify cleanup and repository state:

```bash
orb list  | grep dotgen-test- || true
tart list | grep dotgen-test- || true
git status --short
```

No `dotgen-test-*` guest should remain unless `KEEP_VM=1` was deliberately set.
Only the three implementation/test files and this plan should be changed.

## Risks and non-goals

- A sudoers syntax or include-path mismatch must fail during preparation, before
  the expensive deploy. Do not compensate by weakening generated `sudo -v`.
- Host-derived Orb usernames are data crossing into sudoers syntax. Conservative
  validation and positional/stdin transport are required.
- Tart's known password is a public base-image fixture credential, but it must
  still be excluded from logical command diagnostics and generated output.
- Mocked subprocess tests prove command construction and redaction, not guest
  policy. Non-skipped OrbStack and Tart runs are mandatory acceptance evidence.
- `KEEP_VM=1` intentionally retains the temporary sudoers rule for forensics;
  normal teardown removes the entire guest.
- The separately observed possibility of an SSH readiness probe timing out is
  not part of this sudo fix. Address it in a separate plan if it recurs during
  acceptance testing.

## End state

Real generated bundles still require an interactive regular sudo user and keep
the Plan 12 privilege preflight unchanged. Ephemeral Debian OrbStack, Debian
Docker, and macOS Tart fixtures all satisfy that contract before deployment,
allowing the full VM suite to reach its package, configuration, sandbox, and
idempotency assertions without a terminal password prompt.
