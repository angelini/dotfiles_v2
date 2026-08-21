# dotfiles_v2

A Python build system that emits per-environment Bash bundles for fresh-machine bootstrap.

## Artifact policy

Artifacts are built on the owner's macOS machine and transferred directly to each target. They are never uploaded, published, or hosted. Secrets are not embedded, but bundles contain personal configuration and a sanitized copy of the sibling `pi-angelini` repository, so treat them as private.

## Build on macOS

The `dotfiles_v2` and `pi-angelini` repositories must be siblings unless `DOTGEN_PI_ANGELINI_ROOT` points to the latter.

```bash
just build-all          # all envs → dist/<env>/ + dist/<env>.tar.gz
just build debian       # dist/debian/ + dist/debian.tar.gz
just list               # known envs
just clean              # rm -rf dist
```

`just ci` runs the full chain: `lint typecheck test build-all shellcheck`.

### VM integration tests

VM tests are opt-in and must run from an ordinary, unsandboxed macOS shell. The default `pi` function launches `pi-sandbox`; its macOS Seatbelt profile deliberately excludes the host virtualization state these tests control:

- `/Applications` is not readable, so the `orb` and `docker` symlinks into `OrbStack.app` appear missing.
- `~/.tart` is not readable or writable, so Tart cannot access its image cache, temporary files, or VM state.
- On this host, `uv run` also fails inside the sandbox while canonicalizing `.venv/bin/python3`, before pytest can evaluate its backend skip checks.

The VM recipes therefore no longer run from a normal Pi session by design. Do not add these paths or daemons to the standard sandbox: Docker or OrbStack access can mount arbitrary host paths and would defeat its file isolation. The recipes detect `pi-sandbox` and stop with instructions to retry from a regular terminal or a deliberately unsandboxed `pi-unsafe` session. They are not part of `just ci`.

| Recipe | Host requirements |
| --- | --- |
| `just test-vm debian` | `just`, `uv`, and a running OrbStack installation exposing `orb` |
| `just test-vm debian-docker` | `just`, `uv`, `docker`, and a reachable Docker daemon (normally OrbStack on this Mac) |
| `just test-vm macos` | Apple Silicon, `just`, `uv`, `tart`, `sshpass`, `ssh`, `scp`, and the digest-pinned image from `tests/test_vm_integration.py` already present under `~/.tart/cache/OCIs/` |

Check the selected backend from the same unsandboxed shell that will run the test:

```bash
command -v just uv
command -v orb && orb list                    # Debian VM
command -v docker && docker info               # Debian container
command -v tart sshpass ssh scp                # macOS VM
test "$(uname -m)" = arm64
```

A bare `pytest` executable is not required; `uv run pytest` uses the project development dependency.

### Native Bash and fzf history

Interactive Bash stores plaintext history in `~/.bash_history` with `HISTSIZE=100000`, `HISTFILESIZE=100000`, `HISTCONTROL=ignoreboth`, and `histappend`. Setup creates the file with mode `0600` or tightens an existing regular file without truncating it; unsafe symlink and non-regular paths stop deployment. `ignoreboth` omits commands beginning with a space and immediate duplicates, but it is not secret detection or redaction. Pi continues to hide `.bash_history`.

At every prompt, Bash appends new commands with `history -a` and loads peer additions with `history -n`. This gives already-running shells prompt-bound, best-effort sharing; simultaneous writers can still interleave, duplicate, or lose unflushed commands.

The package-managed standard `fzf --bash` integration supplies `Ctrl-R`, plus its deliberate `Ctrl-T` file picker and `Alt-C` directory picker bindings. `Ctrl-R` starts newest-first with exact newest-preserving deduplication and the current command line as its query; one `--no-sort` is added while retaining fzf's `Ctrl-R` toggle-sort action. A selection replaces or inserts into the command line without submitting it. If fzf is unavailable, shell startup warns once and leaves native `Ctrl-R` unchanged while persistent history and prompt synchronization remain active.

Legacy rollback data is intentionally inert and untouched: `~/bin/stinkpot`, `${XDG_DATA_HOME:-$HOME/.local/share}/stinkpot/history.db` and its `-wal`/`-shm` siblings, and `${XDG_STATE_HOME:-$HOME/.local/state}/dotgen/stinkpot/bash-history-import-v1`. Database history is not imported into Bash, Pi still hides the legacy data directory, and permanent deletion is a manual owner action only.

## Prepare fresh Debian

The generated setup must run as a regular user with sudo, never as root. From the initial administrative shell, create that user if the Debian installer did not already create one:

```bash
apt-get update
apt-get install -y sudo curl ca-certificates tar gzip openssh-server
adduser <user>
usermod -aG sudo <user>
systemctl enable --now ssh
```

Root is used only for this initial OS preparation. Start a login shell as the deployment user and verify the prerequisites:

```bash
su - <user>
sudo -v
curl --version
tar --version
```

If a sudo-capable user already exists, install the prerequisite packages and skip user creation.

## Deploy Debian from the Mac

Build and transfer the sanitized bundle directly from the Mac, then explicitly send the selected environment's secrets:

```bash
just build debian
scp dist/debian.tar.gz <user>@<host>:
uv run python -m dotgen send-secrets debian <user>@<host> --from-file
ssh <user>@<host>
```

`--from-file` without a path reads `${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/secrets.env` on the Mac. An explicit file or exported process-environment values can be used instead:

```bash
uv run python -m dotgen send-secrets debian <user>@<host> --from-file ~/path/to/secrets.env
uv run python -m dotgen send-secrets debian <user>@<host> --from-env
```

Values used by `--from-env` must be exported. Only keys declared by components in the selected environment are sent. The command uses the caller's normal OpenSSH configuration and host-key verification, and atomically installs a mode-`0600` `~/.config/dotgen/secrets.env` under a mode-`0700` directory.

Once secrets exist on the target, rebuild, transfer, extract, and deploy in one command:

```bash
just deploy debian <user>@<host>
```

The command replaces any previously extracted `debian/` bundle, allocates a remote TTY for `sudo -v`, and removes the transferred archive after a successful deployment.

Real values never enter `dist/<env>/` or `dist/<env>.tar.gz`. To provision manually or from a password manager instead, extract the bundle and prepare the target file from its sanitized template:

```bash
tar xzf debian.tar.gz
mkdir -p ~/.config/dotgen
chmod 700 ~/.config/dotgen
cp debian/config/dotgen/secrets.env.template ~/.config/dotgen/secrets.env
chmod 600 ~/.config/dotgen/secrets.env
$EDITOR ~/.config/dotgen/secrets.env
```

Populate manual files using single-line `KEY="value"` entries. Git name and email are required; API keys are needed for their corresponding services. Google model access uses `GEMINI_API_KEY`. Deployment aborts if the file is absent or a required template value is empty.

On Debian, extract the bundle if needed, run it, then start a new login shell:

```bash
tar xzf debian.tar.gz
bash debian/setup.sh deploy
rm debian.tar.gz
exec bash -l
```

The setup preflights non-root execution and sudo authentication before making changes. To install a locally built bundle on the Mac, run `just install macos`.

## Persistent remote agent sessions

The normal `macos` and `debian` environments install tmux and mosh; full Debian also installs Tmuxinator, while `debian-docker` installs none of them. From Ghostty on the Mac, enter either the generic session or a project session:

```bash
mosh-agent <ssh-config-host>                 # plain session: dev
mosh-agent <ssh-config-host> dotfiles_v2     # Tmuxinator project: dotfiles_v2
mosh-agent -k <ssh-config-host>              # end the dev session
mosh-agent -k <ssh-config-host> dotfiles_v2  # end the dotfiles_v2 session
```

A project name maps to an existing real directory at `~/repos/<project>` on the server. Names accept only letters, digits, `_`, and `-`; `dev` is reserved for the generic session. On first use, the Debian helper creates `~/.config/tmuxinator/<project>.yml` from the managed template and starts the project. Later connections attach to the existing session without duplicating windows. The initial layout has a 50/50 `work` window with a shell on the left and `hx .` on the right, followed by a full-window `agents` window running `claude`.

The generic form executes `tmux new-session -A -s dev`; the project form executes `/usr/local/bin/dotgen-agent-session start <project>`. With `-k` they instead execute `tmux kill-session -t =dev` and `dotgen-agent-session kill <project>`; the kill path leaves the generated project config in place, so a later `mosh-agent <host> <project>` starts the same layout again. Mosh uses the existing SSH authentication and then needs inbound UDP 60000–61000 to reach the Debian server. Dotgen does not open host firewalls, cloud security groups, or NAT rules. Use an OpenSSH config host alias for non-default usernames, identity files, or SSH ports. After deployment, perform one real project attachment from the Mac or iOS client; ordinary tests do not traverse the complete SSH-to-mosh-server remote-command path.

Generated project configurations are persistent and are never silently replaced by deployment or connection. To apply a newer managed template, first end the project session after saving its work, then reset its config on the server:

```bash
dotgen-agent-session init <project>   # create config without starting tmux
dotgen-agent-session kill <project>   # end the session, keep the config
dotgen-agent-session reset <project>  # regenerate from the managed template
```

Reset refuses while the exact project session exists. Kill requires it: with no such session it exits 2 and changes nothing. Unlike the other actions, kill needs neither `~/repos/<project>` nor the managed template, so a stale session survives a deleted repository and can still be ended. Tmuxinator does not reconcile config changes into a live session, and ending a session terminates every process in its panes.

Mosh keeps the active terminal responsive and reconnects after sleep, Wi-Fi loss, or a client IP change. Tmux is the persistence boundary: Claude Code, Pi, and other processes in the named session continue after the terminal or mosh client exits. A new `mosh-agent` invocation reattaches. Neither tool preserves a live process across a Debian reboot or tmux server failure.

The `ta [session]` helper attaches or creates a plain session after either SSH or mosh login and switches sessions without nesting when already inside tmux. It defaults to `dev`. Session names accept only letters, digits, `_`, and `-`.

The tmux prefix remains stock `Ctrl-B`. Useful defaults are `Ctrl-B d` to detach, `Ctrl-B w` to choose a project window, `Ctrl-B n` / `Ctrl-B p` for the next or previous window, `Ctrl-B c` for a window, `Ctrl-B |` and `Ctrl-B -` for splits, `Ctrl-B [` for copy mode and retained scrollback, and `Ctrl-B r` to reload `~/.tmux.conf`. New windows and panes inherit the active pane's directory; destroying a session switches its clients to another session when one is available. The stock `%` and `"` split bindings also remain available. Mouse mode is enabled. Hold Shift while selecting in Ghostty to bypass tmux mouse handling and use native terminal selection.

Tmux copy mode and applications inside panes may write the Mac clipboard through OSC 52. This is convenient for trusted agent and editor processes, but any pane process can replace tmux paste buffers and the local clipboard. Mosh supports ordinary OSC 52 and truecolor as of 1.4, but its terminal-state protocol is not a transparent SSH stream. Prefer SSH for large clipboard transfers, image/graphics protocols, port forwarding, or any workflow that needs full terminal-protocol fidelity:

```bash
ssh -t <ssh-config-host> 'tmux new-session -A -s dev'
```

## Rootless Docker on full Debian

Rootless Docker is enabled only by the full `debian` environment, not `debian-docker` or macOS. It requires exact Debian 13 Trixie, the official Docker stable repository, unpinned CE, CLI, containerd, buildx, Compose, and rootless packages, cgroup v2, systemd, logind, and a regular deployment user with sudo used only for host administration. Setup loads the kernel module required by the active iptables backend (`nf_tables` by default or `ip_tables` for legacy iptables) before rootless configuration.

Before deployment, an administrator must inspect the account and every allocated subordinate-ID interval:

```bash
id <user>
cat /etc/subuid
cat /etc/subgid
getsubids <user>
```

Choose non-overlapping contiguous UID and GID intervals of at least 65536 IDs, then allocate them explicitly as administrator actions:

```bash
usermod --add-subuids START-END <user>
usermod --add-subgids START-END <user>
```

Setup validates these ranges but never allocates production ranges. It permanently masks the rootful Docker unit and socket before CE installation, does not grant the `docker` group, and removes conflict packages with `apt remove` semantics only: no purge or data deletion. It does not migrate `/var/lib/docker`, `/var/lib/containerd`, or Podman storage into `~/.local/share/docker`. It enables linger and the user `docker.service`, persists the `rootless` context at `/run/user/<uid>/docker.sock`, and does not set a global `DOCKER_HOST`. Pi sandbox runtime isolation intentionally excludes the Docker socket.

Run user-side checks as the deployment account, without sudo:

```bash
systemctl is-enabled docker.service
systemctl is-active docker.service
systemctl is-enabled docker.socket
systemctl is-active docker.socket
systemctl --user is-enabled docker.service
systemctl --user is-active docker.service
docker context show
docker context inspect rootless
docker info
docker run --rm hello-world
```

Manual remediation is required before rerunning when setup reports state conflicts:

- Reconcile or remove same-ID `/etc/apt/sources.list.d/docker.list` and `/etc/apt/keyrings/docker.gpg`.
- Stop rootful Docker and have an administrator remove a live or stale `/var/run/docker.sock`.
- Manually repair or remove exactly one of the user unit or rootless context.

Setup does not delete these administrator-owned or partial states.

## Pi system

The Pi component installs the Pi CLI/packages, writes managed config under `~/.pi/agent`, and installs the sandbox wrapper. It also bundles a sanitized copy of the sibling `pi-angelini` repository into the artifact and syncs it to `~/repos/pi-angelini` during deploy. The bundle excludes `.git`, `node_modules`, lockfiles, caches, tests, and plan artifacts; Pi then loads it as the local package source `~/repos/pi-angelini`.

Managed Pi config includes Plannotator, the Supacode Pi extension, the `supacode-cli` skill, and the Claude-style scout/planner/reviewer/architect/editor pipeline agents, chain, and prompt. Runtime state and secrets remain intentionally unmanaged: auth files, MCP OAuth tokens, package caches, sessions, memory DBs, Context7 caches, and usage databases are not copied.

On macOS, setup installs the Supacode app via the Homebrew cask.

## Layout

- `src/dotgen/` — package
  - `types.py`, `fragment.py`, `component.py`, `environment.py` — core types
  - `shim.py` — per-OS bash function library (`install_package`, `add_repo`, `download_bin`, …)
  - `render.py` — fragment merge + file emit
  - `bash.py` — quoting/section helpers
  - `components/<name>.py` — each `@dataclass(frozen=True)` implementing `Component`
  - `resources/` — static files copied into generated bundles
- `tests/golden/<env>/` — pinned bundle snapshots; refresh with `UPDATE_GOLDEN=1 just test`

## Add a new environment

Register it in `src/dotgen/registry.py`:

```python
ENVIRONMENTS["alpine"] = Environment(
    "alpine",
    OS.ALPINE,
    PkgMgr.APK,
    components=_SHARED + _LAST,
)
```

`OS.ALPINE` / `PkgMgr.APK` need adding to `types.py`, plus an entry in `_SHIMS` in `shim.py` implementing the full shim contract.

## Add a new component

1. Create `src/dotgen/components/foo.py`:

   ```python
   from dataclasses import dataclass

   from dotgen.environment import Environment
   from dotgen.fragment import Fragment


   @dataclass(frozen=True)
   class Foo:
       name: str = "foo"

       def applies_to(self, env: Environment) -> bool:
           return True

       def render(self, env: Environment) -> Fragment:
           return Fragment(setup="install_package foo\n")
   ```

2. Append `Foo()` to `_SHARED` or an environment-specific tuple in `src/dotgen/registry.py`.
3. Refresh goldens: `UPDATE_GOLDEN=1 just test`. Review the diff.

## Default component composition

`Postgres` is part of `_SHARED`, so normal Debian and macOS deployments install it by default. The smaller `debian-docker` environment excludes Postgres and other development toolchains through `_DOCKER_SKIP`.

## Local dev loop

```bash
just lint               # ruff
just typecheck          # ty
just test               # pytest (90 tests)
just fmt                # ruff format
```

`tests/test_shellcheck.py` runs `shellcheck` against every emitted bundle; skipped if shellcheck is not installed.
