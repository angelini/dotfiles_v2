# dotfiles_v2

A Python build system that emits per-environment Bash bundles for fresh-machine bootstrap.

## Artifact policy

Artifacts are built on the owner's macOS machine and transferred directly to each target. They are never uploaded, published, or hosted. Secrets are not embedded, but bundles contain personal configuration and sanitized copies of the sibling `pi-angelini` and `steps` repositories, so treat them as private.

## Build on macOS

The `dotfiles_v2`, `pi-angelini`, and `steps` repositories must be siblings unless `DOTGEN_PI_ANGELINI_ROOT` and `DOTGEN_STEPS_ROOT` point to their respective checkouts.

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

Populate manual files using single-line `KEY="value"` entries. Git name and email are required; API keys are needed for their corresponding services. Google Vertex model access uses gcloud ADC plus `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` in this file. Deployment aborts if the file is absent or a required template value is empty.

On Debian, extract the bundle if needed, run it, then start a new login shell:

```bash
tar xzf debian.tar.gz
bash debian/setup.sh deploy
rm debian.tar.gz
exec bash -l
```

The setup preflights non-root execution and sudo authentication before making changes. To install a locally built bundle on the Mac, run `just install macos`.

## Prepare and deploy CachyOS

### Supported target and prerequisites

The supported target is a current rolling CachyOS installation identified by `ID=cachyos` and `ID_LIKE=arch` in `/etc/os-release`, on `x86_64`. The tested release snapshot, kernel, desktop session, Pacman version, and optional Shelly UI version are recorded in [`docs/cachyos/live-validation.md`](docs/cachyos/live-validation.md). Other Arch-derived distributions and CachyOS on other architectures are unsupported.

Run deployment as a regular, sudo-capable user, never as root. The host must provide Pacman, systemd as PID 1, logind and a reachable user manager, cgroup v2, SSH for remote deployment and Herdr, and `tar`/gzip for bundle extraction. Shelly is installed by the workstation profile for interactive package management, but deployment automation uses Pacman directly. Run the checked-in secret-free preflight:

```bash
bash docs/cachyos/live-preflight.sh
```

The script prints package versions and sanitized PASS/FAIL results, validates subordinate IDs without printing their values, and exits nonzero on a deployment blocker.

Before enabling rootless Docker, an administrator must inspect `/etc/subuid` and `/etc/subgid` and allocate exactly one non-overlapping UID and GID range of at least 65536 IDs to the deployment user. Dotgen validates but never allocates or repairs these ranges:

```bash
id
getsubids "$USER"
cat /etc/subuid
cat /etc/subgid
# Example only; choose unused START-END values after reviewing all allocations.
sudo usermod --add-subuids START-END "$USER"
sudo usermod --add-subgids START-END "$USER"
```

Also inspect rootful Docker before deployment:

```bash
systemctl is-enabled docker.service docker.socket || true
systemctl is-active docker.service docker.socket || true
sudo stat /var/run/docker.sock 2>/dev/null || true
docker context ls 2>/dev/null || true
```

Stop and remediate any active rootful service, root-owned socket, overlapping subordinate IDs, or partial rootless installation manually. Do not bypass the setup checks.

### Package and artifact policy

CachyOS repository packages use explicit `pacman -S --needed --noconfirm` operations, and deployment performs a full `pacman -Syu --noconfirm` rather than a database-only refresh. Dotgen does not install or update AUR packages unattended. Google Cloud CLI, Doppler, and the rootless Docker launcher use versioned upstream artifacts with pinned SHA-256 digests; Shelly remains available for interactive use. The complete source, version, and verification-command matrix is in [`docs/cachyos/package-sources.md`](docs/cachyos/package-sources.md).

### Build, secrets, transfer, and activation

Build output is `dist/cachyos/` plus `dist/cachyos.tar.gz`:

```bash
just build cachyos
uv run python -m dotgen send-secrets cachyos <user>@<host> --from-file
just deploy cachyos <user>@<host>
```

`send-secrets --from-file` defaults to `${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/secrets.env` on the build host. `--from-file PATH` and `--from-env` work as documented in the Debian procedure. The generated template is `dist/cachyos/config/dotgen/secrets.env.template`; the target file is `~/.config/dotgen/secrets.env`, under a mode-`0700` `~/.config/dotgen` directory and with mode `0600`. It declares `CONTEXT7_API_KEY`, `EXA_API_KEY`, `GIT_USER_EMAIL`, `GIT_USER_NAME`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_CLOUD_PROJECT`, `NPM_TOKEN`, and `ZED_HOST_BRIDGE_SSH_HOST`. The bridge value must be the exact OpenSSH alias used by `herd-remote` and may contain only ASCII letters, digits, dots, and hyphens.

Never put real values in the bundle, Git, logs, or the live-validation record. For manual transfer, either populate the generated template or securely pull an existing secrets file over SSH. This CachyOS-side command stages the file in the owner-only target directory and publishes it atomically:

```bash
(
  set -e
  install -d -m 0700 ~/.config/dotgen
  tmp="$(mktemp ~/.config/dotgen/.secrets.env.XXXXXX)"
  trap 'rm -f -- "$tmp"' EXIT
  scp <build-host>:~/.config/dotgen/secrets.env "$tmp"
  chmod 0600 "$tmp"
  mv -f -- "$tmp" ~/.config/dotgen/secrets.env
  trap - EXIT
)
```

Then extract and deploy:

```bash
tar xzf cachyos.tar.gz
bash cachyos/setup.sh deploy
rm cachyos.tar.gz
exec bash -l
```

If no existing source file is available, copy `cachyos/config/dotgen/secrets.env.template` to the target path with mode `0600` and fill it locally instead.

The preflight validates the OS identity and Pacman before sudo authentication or mutation. After deployment, start a new login shell; do not assess PATH or shell startup from the old shell.

### CachyOS workstation operation

The workstation profile installs Ghostty as `ghostty`, Zed desktop integration with the `zeditor` CLI, Ubuntu and Ubuntu Mono Nerd fonts, and XDG configuration under `${XDG_CONFIG_HOME:-$HOME/.config}`. Herdr installs `herd-local [session-name]` and `herd-remote <ssh-config-host>` plus `~/.config/herdr/{local,remote}.toml`. Both launchers reject extra arguments; `herd-remote` requires exactly one SSH config alias.

CachyOS uses native rootless Docker rather than OrbStack. Dotgen installs Docker, Compose, Buildx, RootlessKit, slirp4netns, fuse-overlayfs, shadow, and iptables from the configured repositories. It downloads the version-pinned upstream Moby `dockerd-rootless.sh` with a pinned SHA-256 digest, installs a managed user service at `~/.config/systemd/user/docker.service`, and removes the obsolete `docker-rootless-extras` AUR package when present. Dotgen also installs `~/.config/systemd/user/docker.service.d/10-dotgen-socket-mode.conf`, enables the user service, creates and selects the explicit `rootless` context, and requires the canonical `unix:///run/user/$UID/docker.sock` to be owned by the deployment user with mode `0600`.

Verify Docker without sudo:

```bash
systemctl is-enabled docker.service docker.socket
systemctl is-active docker.service docker.socket
systemctl --user is-enabled docker.service
systemctl --user is-active docker.service
docker context show
docker context inspect rootless
docker info
docker compose version
docker buildx version
docker run --rm hello-world
stat -c '%U %a %F %n' "/run/user/$UID/docker.sock"
```

The system units must be masked/inactive; `docker context show` must be `rootless`; `docker info` must report rootless security, cgroup v2, and `overlay2` or `fuse-overlayfs`. Pi sandbox configuration deliberately excludes Docker environment passthrough, runtime-directory binds, and Docker sockets, so Docker access from a normal Pi sandbox must fail.

The CachyOS Zed receiver is `~/.config/systemd/user/dev.dotgen.zed-host-bridge.service`. Its local socket is `~/.cache/dotgen/zed-host-bridge.sock`; its SSH include is `~/.ssh/config.d/dotgen-zed-host-bridge.conf`. Deploy the workstation, reconnect `herd-remote` so SSH recreates the remote forward, and use the Debian-side `zed` client. Supported client options are `-n`/`--new`, `-a`/`--add`, `-r`/`--reuse`, `-e`/`--existing`, `-w`/`--wait`, and `--`. Diagnose the receiver and forwarding with:

```bash
systemctl --user status dev.dotgen.zed-host-bridge.service --no-pager
journalctl --user-unit=dev.dotgen.zed-host-bridge.service -n 50 --no-pager
stat -c '%U %a %F %n' ~/.cache/dotgen ~/.cache/dotgen/zed-host-bridge.sock
ssh -G "$ZED_HOST_BRIDGE_SSH_HOST"
```

Restarting the receiver invalidates the existing reverse forward; reconnect `herd-remote` afterward. Setup imports only `WAYLAND_DISPLAY`, `DISPLAY`, `XDG_CURRENT_DESKTOP`, and `DBUS_SESSION_BUS_ADDRESS` when a graphical deployment session supplies a display and D-Bus address. A headless run enables but does not start the receiver until graphical login.

### Composition and recovery boundaries

The CachyOS workstation contains the shared CLI/language/Pi/Steps toolchain plus Linux Herdr workstation launchers, fonts, Ghostty, Zed, native rootless Docker, and the systemd-user Zed receiver. Unlike full Debian it is a workstation receiver rather than a server bridge client; unlike `debian-docker` it is not a minimal container image; unlike macOS it uses XDG paths, systemd user services, native Docker, `zeditor`, and no Homebrew, casks, LaunchAgents, or OrbStack.

Dotgen intentionally refuses to delete or guess through ambiguous state. Manual remediation is required for conflicting or partial Docker markers, rootful units/sockets or storage, invalid subordinate-ID allocations, unsafe/symlinked managed paths, foreign-owned bridge sockets, malformed SSH includes, and failed user-manager or graphical-session prerequisites. It does not delete `/var/lib/docker`, `/var/lib/containerd`, `~/.local/share/docker`, Podman state, unrelated SSH configuration, or application caches. Preserve and inspect state before changing it, then rerun the same reviewed bundle twice. The reusable verification checklist is in [`docs/cachyos/live-validation.md`](docs/cachyos/live-validation.md).

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

The shared Uv and Node components install `uv` and `npm` in every environment. The Steps component bundles the runtime source, Pi extensions, and npm lockfile from the sibling `steps` checkout, copies them to `~/.local/share/steps`, installs locked production npm dependencies with `npm ci --omit=dev`, and installs the `steps` CLI with `uv tool install --reinstall`. Pi loads that same managed source tree for the `/skill:handoff` and `/skill:pipeline` workflows, the trusted `steps.pipeline` workflow resource, and the six package-qualified pipeline agents.

The Pi component installs the Pi CLI/packages, writes managed config under `~/.pi/agent`, and installs the sandbox wrapper. It also bundles a sanitized copy of the sibling `pi-angelini` repository into the artifact and syncs it to `~/repos/pi-angelini` during deploy. The bundle excludes `.git`, `node_modules`, lockfiles, caches, tests, and plan artifacts; Pi then loads it as the local package source `~/repos/pi-angelini`.

Managed Pi config retains the standalone history reviewer, researcher, and session auditor while the Steps package owns its pipeline resources. Runtime state and secrets remain intentionally unmanaged: auth files, MCP OAuth tokens, package caches, sessions, memory DBs, Context7 caches, and usage databases are not copied.

## Herdr launchers

On macOS and CachyOS workstations, `herd-local [session-name]` starts or attaches to a local named session. With no argument it uses the persistent `local` session; supplied names select another persistent session. Local sessions use the Catppuccin Latte theme.

Use `herd-remote <ssh-config-host>` to attach through exactly one host from the OpenSSH config. Remote sessions use the Rosé Pine Dawn theme. Both launchers select dedicated Herdr profiles without changing the configuration used by direct `herdr` invocations.

Debian retains the managed Herdr binary, server configuration, and Reviewr plugin configuration, but receives no convenience launcher.

## Zed host bridge

The full Debian environment installs `~/bin/zed`, which asks the graphical workstation's Zed CLI to open paths through Zed Remote Development. The receiver can be the macOS workstation LaunchAgent or the CachyOS workstation systemd user service. Transport is a reverse Unix-socket forward on the existing `herd-remote <ssh-config-host>` OpenSSH connection; it does not require filesystem mounts, TCP listeners, Docker, or changes to Herdr.

Before deploying either receiver, set `ZED_HOST_BRIDGE_SSH_HOST` in that workstation's dotgen secrets to the exact OpenSSH config alias passed to `herd-remote`. The alias may contain only ASCII letters, digits, dots, and hyphens. Deploy the workstation first, then Debian, and reconnect Herdr so OpenSSH creates the Debian socket. Debian configures `sshd` to replace a stale forwarded socket after a dropped connection:

```bash
# Debian, inside a repository under ~/repos
zed .
zed src/app.py:42:5
zed --new .
zed --wait file.txt
```

Supported options are `-n`/`--new`, `-a`/`--add`, `-r`/`--reuse`, `-e`/`--existing`, `-w`/`--wait`, and `--` before path operands. No operands opens the current directory. stdin, URLs, `--diff`, unknown options, paths outside canonical `~/repos`, and symlink escapes are rejected. Spaces, Unicode, multiple paths, and positive line/column positions are preserved without shell evaluation.

The macOS receiver is the per-user LaunchAgent `dev.dotgen.zed-host-bridge`. Its local socket is `~/Library/Caches/dotgen/zed-host-bridge.sock`. Useful diagnostics are:

```bash
launchctl print gui/$UID/dev.dotgen.zed-host-bridge
ls -l ~/Library/Caches/dotgen/zed-host-bridge.sock
ssh -G "$ZED_HOST_BRIDGE_SSH_HOST" | grep -E '^(remoteforward|exitonforwardfailure)'
```

The CachyOS receiver is `dev.dotgen.zed-host-bridge.service`, installed under `~/.config/systemd/user/`. It runs the managed Node receiver, resolves the packaged `/usr/bin/zeditor` CLI, and uses `~/.cache/dotgen/zed-host-bridge.sock`. Setup imports only `WAYLAND_DISPLAY`, `DISPLAY`, `XDG_CURRENT_DESKTOP`, and `DBUS_SESSION_BUS_ADDRESS` into the user manager, and only when a graphical deployment environment supplies a display and D-Bus address. Diagnose it with:

```bash
systemctl --user status dev.dotgen.zed-host-bridge.service --no-pager
journalctl --user-unit=dev.dotgen.zed-host-bridge.service -n 50 --no-pager
systemctl --user show-environment | grep -E '^(WAYLAND_DISPLAY|DISPLAY|XDG_CURRENT_DESKTOP|DBUS_SESSION_BUS_ADDRESS)='
stat -c '%U %a %F %n' ~/.cache/dotgen ~/.cache/dotgen/zed-host-bridge.sock
ssh -G "$ZED_HOST_BRIDGE_SSH_HOST" | grep -E '^(user|remoteforward|exitonforwardfailure)'
ssh -o ClearAllForwardings=yes "$ZED_HOST_BRIDGE_SSH_HOST" "sudo sshd -T | grep -E '^streamlocalbind(mask|unlink)'"
```

A headless deployment installs and enables the receiver but defers activation until graphical login. With no active Herdr attachment, Debian reports `Zed host bridge unavailable; reconnect with herd-remote <host>`. Only one SSH client can own the forwarded Debian socket for an alias at a time; disconnect and reconnect after changing the alias, restarting the receiver, or replacing a stale connection.

Manual end-to-end verification: confirm both sockets are owned by their users with mode `0600`; run `zed .` and a positioned file from Debian; test every supported behavior and `--wait`; detach Herdr and verify failure; reconnect and verify recovery; restart the workstation receiver and reconnect once more; and confirm no TCP listener was created.

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

`Postgres` and the Terraform tooling are part of the full shared CLI profile, so normal Debian, macOS, and CachyOS deployments install PostgreSQL, Terraform, and Terragrunt by default. Debian installs Terraform from HashiCorp's APT repository and a checksum-pinned Terragrunt binary; macOS uses the documented Homebrew formulas; CachyOS uses the standard `terraform` package plus the same pinned Linux Terragrunt asset. The smaller `debian-docker` environment excludes these and other development toolchains through `_DOCKER_SKIP`.

## Local dev loop

```bash
just lint               # ruff
just typecheck          # ty
just test               # pytest (90 tests)
just fmt                # ruff format
```

`tests/test_shellcheck.py` runs `shellcheck` against every emitted bundle; skipped if shellcheck is not installed.
