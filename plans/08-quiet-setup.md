# Plan 08: Quiet Setup

Setup currently emits a lot of output from tools like `apt-get`, `brew`, `curl`, and `tar`. This makes it hard to see progress and identify actual errors. This plan implements a "quiet by default" mode for the `deploy` command.

## Context

Current `setup.sh` execution is very noisy. We want:

- Each component to echo its name when it starts.
- Subprocess output (stdout/stderr) to be buffered in a temporary file.
- If a component succeeds, show a success indicator and discard the buffer.
- If a component fails, show a failure indicator and dump the buffered output to the CLI.
- `diff` mode should remain unchanged or slightly cleaned up.

## Pre-flight

- [ ] `just ci` passes.

## Tasks

### 1. Update `OSShim` in `src/dotgen/shim.py`

- Ensure `component_begin` and `component_end` are in `SHIM_FUNCTIONS`.
- Implement `component_begin`:
  - In `deploy` mode:
    - Create a temporary file for buffering if not already created.
    - Print the component name (padded for alignment).
    - Save current stdout/stderr (using fds 3 and 4).
    - Redirect stdout/stderr to the buffer file.
  - In `diff` mode:
    - Print a header like `--- <name> ---`.
- Implement `component_end`:
  - In `deploy` mode:
    - Restore stdout/stderr from fds 3 and 4.
    - If exit code is 0, print "DONE" in green.
    - If exit code is non-zero, print "FAIL" in red and `cat` the buffer file.
    - Clear the buffer file for the next component.
  - In `diff` mode:
    - Do nothing (or just a newline).

### 2. Update `render.py` to use component wrappers

- Update `_decorate` to wrap the `frag.setup` block.
- The wrapper should look like this in the generated bash:
  ```bash
  component_begin "component_name"
  if (
    set -e
    # original component setup code
  ); then
    component_end "component_name" 0
  else
    rc=$?; component_end "component_name" "$rc"; exit "$rc"
  fi
  ```
- This subshell approach ensures `set -e` failures are caught and handled by `component_end` before the main script exits.

### 3. Cleanup `render.py` constants

- Update `SETUP_HEADER` and `SETUP_FOOTER` if they contain redundant logging that conflicts with the new per-component status lines.

### 4. Verify and Snapshot

- Run `just build-all` to see the generated code.
- Run `just test` to see the diff in goldens.
- Update goldens with `UPDATE_GOLDEN=1 just test` if the output looks correct.

## Critical Files

- `src/dotgen/shim.py`
- `src/dotgen/render.py`

## Verification

- `just ci` (ensures lint/typecheck/shellcheck pass)
- Inspect `dist/debian/setup.sh` manually to verify the wrapping logic.
- Run `dist/debian/setup.sh deploy` (on a test machine or VM) to verify the visual experience.
