# Plan 12 — Debian bootstrap hardening

## Context

A generated Debian bundle is built privately on the owner's macOS machine and
transferred directly to a fresh Debian host. Bundles are not published or
hosted.
The target runs `setup.sh deploy` as a regular user with sudo; root is reserved
for initial OS and user preparation.

The current bootstrap has four correctness and documentation gaps:

1. FNM is installed, but no Node release is activated in the running setup
   process before Pi invokes npm.
2. `just install <env>` omits the required `deploy` mode.
3. The README documents stale registry and Postgres behavior and does not
   describe the private Mac-to-Debian workflow.
4. The Debian shim falls back to direct privileged execution when sudo is
   absent, conflicting with the deployment policy.

## Decisions

- Install and activate the latest Node LTS with FNM.
- Enforce non-root, sudo-authenticated execution for every `deploy`, including
  macOS.
- Keep initial Debian root preparation and test-container root administration
  outside the generated deployment policy.
- Build artifacts only on the owner's macOS machine and transfer them directly
  to targets.
- Keep `debian-docker`'s Pi installation, so it must also include `node_fnm`
  before `pi_agent`.

## Pre-flight

- Preserve the existing uncommitted Pi/Supacode work.
- Verify the installed Pi package Node engine requirement.
- Verify current FNM syntax for installing and activating latest LTS.
- Review generated snapshot changes before accepting them.

## Tasks

### 1. Install and activate Node

Update `src/dotgen/components/node_fnm.py` so deploy mode:

- exposes the FNM binary in the current setup process;
- evaluates `fnm env --shell bash`;
- runs `fnm install --lts --use` before `pi_agent` executes.

Keep these commands behind the deploy guard so `setup.sh diff` does not invoke
an FNM binary that has only been reported, not installed. Use an explicit Bash
shell in the generated `.bashrc` FNM initialization.

Remove `node_fnm` from the Debian Docker skip set. Add a component-order
invariant: every environment containing `pi_agent` contains `node_fnm` earlier
in the sequence.

### 2. Fix local install dispatch

Change `just install <env>` to invoke:

```bash
bash dist/<env>/setup.sh deploy
```

Add a regression assertion for the recipe text or dry-run output.

### 3. Enforce regular-user deployment

In the generated setup header, before quiet component execution:

- reject UID 0;
- require `sudo`;
- run `sudo -v` so authentication is visible and cached;
- continue with gettext and secrets checks only after privilege preflight
  succeeds.

Simplify Debian privileged operations to always use sudo:

- package installation;
- APT repository/keyring writes;
- package index updates;
- service enablement.

Retain Docker build-time root commands and Docker test-harness ownership repair.
They administer an image/container and do not execute the user bootstrap as
root.

### 4. Update documentation

Rewrite README deployment guidance to distinguish:

1. one-time Debian administrative preparation;
2. private artifact build on the owner's Mac;
3. direct SCP/SSH transfer;
4. secrets population;
5. non-root deployment and login-shell activation.

Document required Debian preparation packages and sudo-user creation. State
that artifacts are never hosted or published. Remove the claim that the artifact
is safe to publish. Correct component registration from `environment.py` to
`registry.py`, update the component example, and document Postgres as a default
shared component.

### 5. Add regression coverage

Add tests for:

- FNM current-process activation and latest-LTS Node installation;
- `node_fnm` preceding `pi_agent` in every relevant environment;
- Debian Docker retaining `node_fnm`;
- generated deploy preflight rejecting root and requiring sudo;
- unconditional sudo use in Debian privileged shim functions;
- `just install` passing `deploy`;
- Node and npm availability in VM integration tests.

Refresh golden snapshots and inspect every generated Bash change.

## Critical files

- `src/dotgen/components/node_fnm.py`
- `src/dotgen/registry.py`
- `src/dotgen/render.py`
- `src/dotgen/shim.py`
- `justfile`
- `README.md`
- `tests/test_components.py`
- `tests/test_shim.py`
- `tests/test_setup_dispatcher.py`
- `tests/test_vm_integration.py`
- `tests/golden/`

## Verification

```bash
UPDATE_GOLDEN=1 just test
git diff -- tests/golden/
just ci
just test-vm debian
just test-vm debian-docker
```

VM tests remain opt-in and may skip when their backend is unavailable. A skipped
VM run must be reported rather than treated as runtime proof.

## End state

A fresh Debian host can be prepared with a regular sudo user, receive a
privately built bundle from the owner's Mac, and complete deployment with
Node/npm available before Pi installation. Root execution is rejected,
privileged operations consistently use sudo, local installs pass an explicit
mode, and the README matches the implemented workflow.
