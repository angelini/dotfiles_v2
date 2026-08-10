# Plan 18 — Persistent remote agent sessions with tmux and mosh

## Goal

Install and configure tmux and mosh on the normal macOS and Debian environments, while excluding both from `debian-docker`. The primary workflow is Ghostty on macOS connecting to Debian and entering a named tmux session where long-running Claude Code or Pi processes survive client sleep, Wi-Fi loss, and terminal closure.

## Context and upstream assessment

The roles are intentionally separate:

- tmux owns the durable server-side processes and scrollback. A tmux session survives loss of its attached client, but not a Debian reboot or tmux server failure.
- mosh is a replaceable interactive transport. It authenticates with SSH, then uses an unprivileged mosh server over UDP. It can resume after sleep, client IP changes, and intermittent connectivity.
- Ghostty is the local terminal. Its existing component enables SSH environment and terminfo integration. Ghostty uses `xterm-ghostty`, permits OSC 52 clipboard writes by default, and lets Shift bypass application mouse reporting for native selection.

Primary sources:

- Ghostty SSH and terminfo behavior: <https://ghostty.org/docs/features/ssh>
- Ghostty clipboard and mouse options: <https://ghostty.org/docs/config/reference>
- tmux terminal, RGB, mouse, and escape-time guidance: <https://github.com/tmux/tmux/wiki/FAQ>
- tmux OSC 52 model and security implications: <https://github.com/tmux/tmux/wiki/Clipboard>
- mosh roaming, sleep, and UDP behavior: <https://mosh.org/> and <https://manpages.debian.org/trixie/mosh/mosh.1.en.html>
- mosh 1.4 truecolor and OSC 52 support: <https://mosh.org/mosh-1.4.0-released.html>
- tmux-over-mosh OSC 52 interoperability: <https://github.com/tmux/tmux/issues/3423>

A Debian Trixie container pre-flight confirmed tmux 3.5a, mosh 1.4.0, the `tmux-256color` terminfo entry, and successful parsing of the selected `terminal-features`, `terminal-overrides`, `set-clipboard`, `escape-time`, mouse, focus, and history settings.

## Decisions

- Keep tmux's stock `C-b` prefix.
- Permit applications inside tmux to write the local clipboard with OSC 52 by setting `set-clipboard on`. This intentionally lets pane applications create or replace tmux paste buffers and replace the Mac clipboard.
- Use a fixed OSC 52 clipboard selector for mosh's `xterm` and `xterm-256color` identities. Direct Ghostty retains its native `xterm-ghostty` clipboard capability.
- Use `tmux-256color` inside tmux and explicitly advertise RGB and clipboard support for direct Ghostty and mosh outer terminals.
- Enable mouse handling, focus events, 100,000 lines of tmux history per pane, and a 10 ms Escape delay. Do not add plugins, themes, status customization, prefix changes, vi-mode assumptions, automatic tmux startup, or reboot resurrection.
- Add `ta [session]` on normal macOS and Debian. It defaults to `agents`, attaches or creates outside tmux, and switches sessions without nesting inside tmux.
- Add `mosh-agent <host> [session]` on macOS only. It defaults to `agents` and executes tmux directly as the mosh remote command.
- Restrict helper session names to ASCII letters, digits, `_`, and `-`. This keeps tmux target matching and remote argv behavior unambiguous.
- Use the normal mosh UDP range, 60000–61000. Dotgen does not modify host firewalls, cloud security groups, NAT, SSH configuration, or Tailscale configuration.
- Prefer mosh for roaming text sessions. Use SSH when UDP is unavailable or terminal-protocol fidelity, large clipboard transfers, graphics/image protocols, or port forwarding matter more than roaming.

## Scope

- Add separate frozen `Tmux` and `Mosh` components.
- Install both packages through `install_package` on `debian` and `macos`.
- Install a generated tmux configuration as `~/.tmux.conf`.
- Emit `ta` in both normal environments and `mosh-agent` only on macOS.
- Register both in `_SHARED`, add both to `_DOCKER_SKIP`, and make each component's `applies_to()` reject `debian-docker` independently.
- Add focused component and helper tests, update distribution tests, refresh snapshots, add VM assertions, and document usage.

## Out of scope

- Opening UDP ports or changing SSH/server security policy.
- Embedding a hostname, username, identity path, SSH port, or mosh UDP port.
- tmux plugins such as resurrect/continuum, TPM, themes, or agent-status integrations.
- Preserving live processes across a Debian reboot.
- Making Kitty graphics, image paste, or arbitrary terminal passthrough work through mosh.
- Replacing SSH for file transfer, tunnels, port forwarding, or non-interactive commands.
- Adding tmux or mosh to `debian-docker`.

## Steps

### 1. Add the Tmux component

Create `src/dotgen/components/tmux.py`.

The generated config must contain:

```tmux
set -g default-terminal "tmux-256color"
set -as terminal-features ",xterm-ghostty:RGB:clipboard"
set -as terminal-features ",xterm-256color:RGB:clipboard"
set -as terminal-features ",xterm:RGB:clipboard"
set -as terminal-overrides ",xterm-256color:Ms=\\E]52;c%p1%s;%p2%s\\007"
set -as terminal-overrides ",xterm:Ms=\\E]52;c%p1%s;%p2%s\\007"
set -s set-clipboard on
set -s escape-time 10
set -g focus-events on
set -g mouse on
set -g history-limit 100000
```

Do not set `allow-passthrough`: tmux's clipboard path does not require general terminal passthrough, and mosh does not carry arbitrary graphics protocols reliably.

The setup contribution installs `tmux` and copies `config/tmux/tmux.conf` to `~/.tmux.conf` with `install_config`.

The alias contribution defines `ta [session]`. It must:

- accept zero or one argument and default to `agents`;
- reject empty or unsafe names and extra arguments with status 2 before invoking tmux;
- use `-t "=$session"` for exact `has-session` and `switch-client` targets;
- run `tmux new-session -A -s <session>` outside tmux;
- switch to an existing session inside tmux, or create it detached and then switch, rather than nesting a second client.

### 2. Add the Mosh component

Create `src/dotgen/components/mosh.py`.

The setup contribution is `install_package mosh`. The macOS alias contribution defines `mosh-agent <host> [session]`; Debian receives no `mosh-agent` function because it is the server side of this workflow.

The helper must:

- accept one or two arguments and default the session to `agents`;
- reject an empty or leading-dash host, unsafe session names, and extra arguments with status 2 before invoking mosh;
- execute `command mosh -- "$host" tmux new-session -A -s "$session"` so the remote command does not depend on remote aliases or shell startup files;
- preserve the host and session as single argv entries.

### 3. Register and exclude the components

Update `src/dotgen/registry.py` to import both classes, place `Tmux()` then `Mosh()` after `Stinkpot()` in `_SHARED`, and add `tmux` and `mosh` to `_DOCKER_SKIP`.

Both `applies_to()` implementations must independently return true only for environment names `debian` and `macos`.

### 4. Add focused tests

Add `tests/test_tmux_mosh_components.py` and extend `tests/test_components.py`.

Cover:

- exact environment applicability and registry counts;
- complete Docker exclusion;
- setup/config destinations and config mode;
- stock-prefix preservation and exact terminal/clipboard/mouse/focus/history/Escape settings;
- absence of plugins, passthrough, automatic startup, and vi-mode customization;
- helper default/named behavior using fake shell commands that record NUL-delimited argv;
- inside-tmux switch/create behavior;
- invalid arity, empty or leading-dash hosts, and empty, Unicode, or otherwise unsafe session names returning 2 without command execution;
- macOS-only emission of `mosh-agent`.

Ordinary tests must not install packages, open SSH connections, or use UDP.

### 5. Refresh and inspect generated output

Regenerate snapshots after focused tests pass.

Expected changes:

- `debian` and `macos` `setup.sh`: tmux and mosh sections;
- `debian` and `macos` `alias.sh`: `ta`;
- `macos/alias.sh`: `mosh-agent`;
- `debian` and `macos` `config-manifest.txt`: `tmux/tmux.conf`.

Expected unchanged:

- every `debian-docker` golden;
- all generated `.bashrc` and `os_shim.sh` files;
- `src/dotgen/shim.py` and `tests/test_shim.py`.

Read the complete golden diff before retaining it.

### 6. Add runtime acceptance and documentation

Extend VM coverage for normal environments to assert package availability, helper definitions, deployed config equality, `tmux-256color` availability, config loading, and `TERM=tmux-256color` inside a detached session. Use an isolated socket such as `tmux -L dotgen-test` and kill that server after each check so existing state cannot mask configuration failures. Track `~/.tmux.conf` in redeploy idempotency checks. Generated `debian-docker` output must contain no tmux or mosh component.

Update `README.md` with the connection workflow, stock keys, Shift-to-select behavior in Ghostty, the requirement for inbound UDP 60000–61000 to the remote server, clipboard security boundary, SSH fallback, and the distinction between mosh reconnection and tmux process persistence.

Manual Ghostty acceptance:

1. Run `mosh-agent <ssh-config-host>` from Ghostty.
2. Start a long-running command or agent and note the tmux session.
3. Close/sleep the Mac or change networks, then reconnect and verify the process remains.
4. Verify RGB rendering and ordinary OSC 52 copy through both SSH+tmux and mosh+tmux.
5. Verify tmux copy-mode/mouse scrollback uses the retained 100,000-line history.
6. Hold Shift for native Ghostty selection when tmux mouse mode is active.
7. Use SSH instead of mosh for a large clipboard transfer or terminal graphics workflow.

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
rg -n 'tmux|mosh' dist/debian-docker/setup.sh dist/debian-docker/alias.sh
find dist/debian-docker/config -path '*tmux*' -print
```

Both commands must return no matches.

Optional runtime acceptance:

```bash
just test-vm debian
just test-vm debian-docker
just test-vm macos
```

## Risks and constraints

- `set-clipboard on` lets untrusted pane applications create or replace tmux paste buffers and replace the local clipboard.
- Mosh's OSC 52 support and datagram-oriented design can limit large clipboard transfers; SSH is the high-fidelity fallback.
- Mosh requires reachable UDP after SSH authentication. Installation alone cannot guarantee network reachability.
- A 10 ms Escape delay is a compromise. Raise it if realistic mosh use splits Alt/meta sequences.
- `tmux-256color` must exist on the host running applications inside tmux; the Trixie package pre-flight passed.
- A tmux session does not survive host reboot, process kill, resource exhaustion, or tmux server failure.

## End state

Normal macOS and Debian bundles install tmux and mosh. Ghostty users can run `mosh-agent host [session]` from the Mac or `ta [session]` after connecting. The named tmux session retains agents and pane history independently of the client transport, while mosh makes the active terminal tolerant of sleep, roaming, and intermittent Wi-Fi. The Debian container bundle remains unchanged and contains neither component.
