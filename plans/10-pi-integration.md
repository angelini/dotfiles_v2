# Plan 10: Integrate Pi Coding Agent

This plan integrates the `pi` coding agent (pi.dev) into the dotfiles development environment as a standard component.

## Context

`pi` is a minimalist coding agent harness. We want to provide it as a standard tool in our `debian` and `macos` environments, alongside our existing CLI toolchain.

## Tasks

### 1. Extend the Shim (`src/dotgen/shim.py`)

- The `pi` agent is typically installed via `npm`.
- Ensure we have a robust way to install global npm packages or use the standalone installer.
- Update `SHIM_FUNCTIONS` if a new helper (e.g., `install_npm_global`) is required.

### 2. Create the `Pi` Component (`src/dotgen/components/pi_agent.py`)

- **Name**: `pi_agent`
- **Setup**:
  - Ensure `node` (via `node_fnm`) is a dependency.
  - Install `pi` via `npm install -g @earendil-works/pi-coding-agent`.
  - Alternatively, use the `curl | bash` quickstart if preferred.
- **Config**:
  - Emit a default `~/.pi/config.json` if necessary.
  - Potentially link `repos/lpi/AGENTS.md` as a global instruction set.

### 3. Update Registry (`src/dotgen/registry.py`)

- Add `PiAgent()` to `_SHARED` or `_FULL_ADDONS`.
- Since it depends on `node_fnm`, ensure correct ordering in the component tuple.

### 4. Verification

- `just build-all`
- `just test` (snapshot check)
- `just test-vm debian` (verify installation)

## Critical Files

- `src/dotgen/shim.py`
- `src/dotgen/components/pi_agent.py`
- `src/dotgen/registry.py`

## Verification

- `pi --version` in a fresh environment.
