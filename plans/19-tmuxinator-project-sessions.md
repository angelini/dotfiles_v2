# Plan 19 — Tmuxinator project sessions over mosh

## Status

Implemented and CI-validated. Optional VM execution and manual real-mosh acceptance remain. This plan supersedes only the two-argument `mosh-agent` behavior from Plan 18; Plan 18 remains the implementation history for tmux and mosh.

## Goal

Add Debian-side Tmuxinator project sessions that are created on first use and reattached through mosh. Preserve `mosh-agent <host>` as the generic `dev` tmux session. Change `mosh-agent <host> <project>` to initialize a persistent project configuration on the server when needed, then enter the Tmuxinator-managed session.

Each generated project starts with exactly two windows:

1. `work`: a 50/50 left-right split with an interactive shell on the left and `hx .` on the right, initially focused on the shell.
2. `claude`: one full-window pane running `claude`.

## Context and upstream assessment

Tmuxinator creates tmux sessions from YAML. It runs where the tmux server and agent processes live, so only the full Debian environment needs it. macOS and iOS remain mosh clients.

Primary sources:

- Tmuxinator installation, YAML, hooks, ERB, and CLI: <https://github.com/tmuxinator/tmuxinator>
- Debian Trixie package, version 3.3.3: <https://packages.debian.org/trixie/tmuxinator>
- Tmuxinator project/session behavior: <https://github.com/tmuxinator/tmuxinator/blob/master/lib/tmuxinator/project.rb>
- Tmuxinator generated startup behavior: <https://github.com/tmuxinator/tmuxinator/blob/master/lib/tmuxinator/assets/template.erb>
- Mosh remote-command behavior: <https://manpages.debian.org/trixie/mosh/mosh.1.en.html>

Tmuxinator creates the configured windows and runs their commands only when the named tmux session does not already exist. A later start attaches or switches to the existing session; it does not reconcile layout changes into a live session. Stopping the session terminates all processes in its panes.

## Approved decisions

- Install Tmuxinator only in the full `debian` environment, not on macOS or in `debian-docker`.
- Preserve `mosh-agent <host>` as `mosh -- <host> tmux new-session -A -s dev`.
- Interpret the second argument as a project: `mosh-agent <host> <project>`.
- Map project `<project>` to the existing real directory `~/repos/<project>`.
- Restrict project names to ASCII letters, digits, `_`, and `-`, reject a leading dash, and match the existing helper contract.
- Reserve `dev`; it cannot be used as a Tmuxinator project name.
- Reject missing project directories and reject a project root that is a symlink. The helper never creates or clones repositories.
- Install a managed scaffold separately from generated project files.
- Create a persistent project config only when absent. Never overwrite it during ordinary connection or dotfiles redeploy.
- Apply future scaffold changes through an explicit manual reset command. Reset must refuse while the project tmux session exists and must replace the config atomically only after successful rendering.
- Use exactly two initial windows: `work` and `claude`.
- Use `layout: even-horizontal` for the 50/50 `work` split.
- Put the blank interactive shell in the first/left pane and run `hx .` in the second/right pane. Tmuxinator 3.3.3 always selects the first pane, and `startup_pane: 0` preserves shell focus without the newer `focused_pane` key.
- Run `claude` in the sole pane of the second window.
- Do not add Tmuxinator hooks, automatic test commands, monitoring windows, plugins, secrets, or reboot resurrection.

## Command contract

### Client helper

```text
mosh-agent <host>
mosh-agent <host> <project>
```

- One argument enters the plain `dev` session.
- Two arguments execute the server helper directly through mosh:

```text
/usr/local/bin/dotgen-agent-session start <project>
```

The absolute path avoids dependence on non-interactive remote `PATH`, aliases, or shell startup files. Host and project remain separate argv entries; do not construct an interpolated remote shell command.

### Server helper

```text
dotgen-agent-session init <project>
dotgen-agent-session start <project>
dotgen-agent-session reset <project>
```

- `init` validates the project and creates its config if missing, then exits.
- `start` performs the same safe initialization and executes `tmuxinator start <project>`.
- `reset` refuses when an exact tmux session named `<project>` exists, renders a replacement config to a temporary file, atomically replaces the persistent config, and exits without starting the session.

All subcommands accept exactly one project argument. Invalid names, `dev`, missing roots, symlink roots, unexpected config file types, and extra arguments fail with status 2 before Tmuxinator starts.

## Managed and persistent files

Managed by dotgen and replaced on deploy:

```text
${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/tmuxinator/default.yml
/usr/local/bin/dotgen-agent-session
```

Created by the server helper and never replaced automatically:

```text
${XDG_CONFIG_HOME:-$HOME/.config}/tmuxinator/<project>.yml
```

The managed scaffold uses Tmuxinator's supported ERB variables:

```yaml
name: <%= name %>
root: ~/repos/<%= name %>

startup_window: work
startup_pane: 0

windows:
  - work:
      layout: even-horizontal
      panes:
        - shell:
        - editor: hx .
  - claude: claude
```

The scaffold must remain free of secrets and host-specific credentials. Pane commands are sent to an interactive shell; exiting Helix or Claude returns to that shell.

## Safety and lifecycle

The server helper must:

1. Validate subcommand and project before filesystem changes.
2. Resolve the project root as exactly `$HOME/repos/$project`.
3. Require `$HOME/repos` and the project root to be real directories, not symlinks.
4. Require the managed scaffold to be a regular non-symlink file.
5. Require an existing persistent project config to be a regular non-symlink file.
6. Serialize creation/reset with `flock` on a persistent lock file under `${XDG_STATE_HOME:-$HOME/.local/state}/dotgen/`. Release only the lock/file descriptor; never unlink the lock path, because a replacement inode would defeat serialization.
7. Render in a temporary directory by placing the managed scaffold there as `default.yml` and invoking `EDITOR=true TMUXINATOR_CONFIG=<temporary-directory> tmuxinator new <project>`.
8. Before replacement, require the rendered candidate to be a regular non-symlink file and run `TMUXINATOR_CONFIG=<temporary-directory> tmuxinator debug <project>` successfully. This makes Tmuxinator 3.3.3 parse the YAML and render its generated shell commands.
9. Install the validated candidate with mode `0644` and atomically rename it into the persistent config directory while holding the lock.
10. Preserve an existing config byte-for-byte during `init`, `start`, and redeploy.
11. Refuse first-time initialization if an exact tmux session with the same name already exists, because Tmuxinator would attach without building the configured layout.
12. Refuse `reset` while the exact project session exists; never kill or replace a running project automatically.

Temporary render directories and files must be cleaned on success, failure, and interruption. The persistent lock file remains in place; closing its locked file descriptor releases the lock. Error messages must identify the invalid project, missing root, collision, or unsafe file without exposing secrets.

## Scope

- Add a frozen Debian-only `Tmuxinator` component.
- Install the Debian package through `install_package tmuxinator`.
- Bundle and deploy the managed default scaffold.
- Bundle the server helper with executable mode and install it to `/usr/local/bin` with explicit diff/deploy behavior.
- Update the macOS `mosh-agent` function with arity-dependent generic/project routing.
- Register the component only in the full Debian environment.
- Add focused unit tests, snapshot updates, VM assertions, shellcheck coverage, and user documentation.

## Out of scope

- Creating, cloning, pulling, or selecting repositories.
- Supporting project names containing dots, slashes, spaces, or Unicode.
- Supporting symlinked project roots.
- Migrating the generic `dev` session to Tmuxinator.
- Automatically modifying existing project configs when the scaffold changes.
- Automatically killing sessions to apply a new layout.
- Per-project test, server, log, or monitoring windows in the initial scaffold.
- Tmuxinator on macOS or `debian-docker`.
- tmux plugins, process supervision, or persistence across Debian reboot.

## Steps

### 1. Add the Tmuxinator component

Create `src/dotgen/components/tmuxinator.py` with:

- the exact managed YAML scaffold;
- the executable Bash server helper;
- setup text that installs `tmuxinator`, deploys the scaffold under the user's XDG config root, and installs the helper at `/usr/local/bin/dotgen-agent-session`;
- `applies_to()` returning true only for `env.name == "debian"`;
- `ConfigFile` modes `0644` for the scaffold and `0755` for the bundled helper.

The helper installer must support dotgen `diff` and `deploy`, reject unsafe source/destination types, compare content and mode, and use `sudo install` only during deploy. Do not extend the cross-OS shim unless the implementation proves a reusable helper is necessary.

### 2. Register the Debian-only component

Update `src/dotgen/registry.py` to import `Tmuxinator` and place `Tmuxinator()` before `Docker()` in `_DEBIAN_FULL`.

Do not add it to macOS, `_SHARED`, or the Docker environment. Keep the component's own applicability check so direct rendering also rejects unsupported environments.

### 3. Update `mosh-agent`

Modify `src/dotgen/components/mosh.py` so:

- one argument preserves the current generic `dev` remote argv exactly;
- two arguments validate the project, reject `dev`, and invoke `/usr/local/bin/dotgen-agent-session start <project>`;
- invalid host, invalid project, and extra arguments return 2 before invoking mosh;
- project and host remain separate argv entries.

Update the usage string to describe `<project>` rather than a generic optional session.

### 4. Add focused tests

Extend `tests/test_tmux_mosh_components.py` and the broad component registry tests.

Cover:

- Debian-only applicability, registry count/order, and complete Docker/macOS exclusion;
- exact setup destinations and bundled file modes;
- exact scaffold content and ordering: two windows only, first/left blank shell pane, second/right `hx .` pane, `even-horizontal`, `startup_pane: 0`, and one full-window `claude` command; do not add a Python YAML dependency solely for this test;
- generic one-argument mosh argv remaining unchanged;
- exact two-argument remote helper argv;
- rejection of `dev`, empty, leading-dash, dotted, slashed, spaced, Unicode, and extra project arguments;
- server helper `init`, `start`, and `reset` behavior using a temporary home and fake `tmux`, `tmuxinator`, and lock commands;
- missing and symlink project roots;
- unsafe managed/persistent config file types;
- first creation, existing-config preservation, collision with a pre-existing tmux session, atomic reset, and reset refusal while active;
- failure cleanup and no tool invocation after validation errors.

Ordinary tests must not install packages, start a real tmux server, open SSH, or use UDP.

### 5. Extend shellcheck and snapshots

Ensure the bundled server helper is included by `tests/test_shellcheck.py` and the `just shellcheck` target even though it is nested below `dist/debian/config/` and installed without a `.sh` suffix.

Regenerate snapshots only after focused tests pass. Expected changes:

- Debian `setup.sh`: new Tmuxinator component section.
- Debian `config-manifest.txt`: managed scaffold and executable helper.
- macOS `alias.sh`: project routing in `mosh-agent`.
- Relevant golden tests that assert registry/package output.

Expected unchanged:

- every `debian-docker` Tmuxinator-related output;
- macOS setup and config manifest for Tmuxinator;
- tmux configuration and `ta` behavior;
- the generic one-argument mosh remote argv.

Read the complete golden diff before retaining it. Preserve unrelated worktree changes already in progress.

### 6. Add runtime acceptance and documentation

Extend Debian VM coverage to assert:

- `tmuxinator` is installed;
- `/usr/local/bin/dotgen-agent-session` is executable and equals the bundled helper;
- the managed scaffold equals the bundled source;
- `init` creates a valid project config for a disposable real directory;
- repeated `init` leaves a sentinel config byte-for-byte unchanged;
- `tmuxinator debug <project>` parses the generated YAML and contains two windows, the expected split/layout, `hx .`, and `claude`;
- a disposable `tmuxinator start --no-attach <project>` creates exactly the `work` and `claude` windows; `work` has two panes with widths differing by at most one column, pane 0 is active, and both panes use the project working directory;
- test-only `hx` and `claude` executables placed first on `PATH` print distinct markers and remain alive, allowing pane capture to prove both startup commands ran without depending on interactive credentials;
- a second detached start keeps the same two windows and does not duplicate panes;
- reset refuses while the exact disposable tmux session exists;
- cleanup removes the disposable session, fake executables, repo, and config.

Generated Docker output must contain no Tmuxinator package, scaffold, or helper. macOS output must contain only the updated client alias, not the package or server files.

Update `README.md` with:

- generic versus project `mosh-agent` behavior;
- the `~/repos/<project>` convention;
- automatic first-use initialization;
- the two-window layout and key navigation;
- `dotgen-agent-session init/reset` usage;
- the warning that reset never updates a running session and that stopping a session terminates its agents;
- manual real-mosh acceptance because argv serialization and remote execution are not fully exercised by ordinary tests.

## Verification

```bash
uv run pytest tests/test_tmux_mosh_components.py tests/test_components.py -v
uv run ruff check src tests
uv run ty check src
UPDATE_GOLDEN=1 uv run pytest tests/test_render_snapshot.py -v
git diff -- tests/golden/
just build-all
just shellcheck
just ci
git diff --check
git status --short
```

Container exclusion checks:

```bash
rg -n 'tmuxinator|dotgen-agent-session' dist/debian-docker
find dist/debian-docker/config -path '*tmuxinator*' -print
```

Both commands must return no matches.

Optional runtime acceptance:

```bash
just test-vm debian
just test-vm debian-docker
```

Manual client acceptance:

1. Ensure a real `~/repos/<project>` directory exists and no same-named tmux session exists.
2. Run `mosh-agent <host> <project>` from Ghostty.
3. Verify `work` opens first with shell left, Helix right, equal pane widths, and pane 0/shell focus.
4. Verify `claude` is the second window and occupies one full pane.
5. Detach and reconnect with the same command; verify the existing Claude process survives and no duplicate windows appear.
6. Verify `mosh-agent <host>` enters the generic `dev` session.
7. Verify an iOS mosh client can invoke the same absolute remote helper command.
8. Exit the project session, run `dotgen-agent-session reset <project>`, reconnect, and verify the scaffold is regenerated.

## Risks and constraints

- Tmuxinator does not reconcile YAML changes into an existing tmux session.
- Resetting config does not affect a live session; rebuilding the live layout requires intentionally ending that session, which terminates its processes.
- A stale plain tmux session with the project name prevents correct first-time layout creation and must be handled manually.
- The global helper path requires sudo during deployment; deploy must never replace an unsafe non-regular destination.
- Generated project YAML is user-owned after creation. Future dotfiles deploys update only the managed scaffold.
- `flock` serializes helper-mediated creation/reset on Debian. Its lock pathname must persist; direct manual edits remain the user's responsibility.
- Real mosh acceptance remains necessary to validate the full client/SSH/mosh-server command path.

## End state

`mosh-agent host` enters the generic `dev` session. `mosh-agent host project` validates a real `~/repos/project`, invokes the Debian server helper, creates `~/.config/tmuxinator/project.yml` from the managed scaffold on first use, and starts or reattaches the project session. The project opens with a 50/50 shell-and-Helix work window followed by a full-window Claude session. Existing project configs and running sessions are never silently overwritten or killed.
