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

Build and transfer directly from the Mac:

```bash
just build debian
scp dist/debian.tar.gz <user>@<host>:
ssh <user>@<host>
```

On Debian, extract the bundle and prepare its per-machine secrets file:

```bash
tar xzf debian.tar.gz
mkdir -p ~/.config/dotgen
chmod 700 ~/.config/dotgen
cp debian/config/dotgen/secrets.env.template ~/.config/dotgen/secrets.env
chmod 600 ~/.config/dotgen/secrets.env
$EDITOR ~/.config/dotgen/secrets.env
```

Populate values from the password manager using single-line `KEY="value"` entries. Git name and email are required; API keys are needed for their corresponding services. Google model access uses `GEMINI_API_KEY`. Deployment aborts if the file is absent or a required template value is empty.

Run the generated bundle, then start a new login shell:

```bash
bash debian/setup.sh deploy
rm debian.tar.gz
exec bash -l
```

The setup preflights non-root execution and sudo authentication before making changes. To install a locally built bundle on the Mac, run `just install macos`.

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
