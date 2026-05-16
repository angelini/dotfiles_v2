# Plan 11: Pi Sandboxing with Seatbelt and bwrap

This plan designs an OS-specific sandbox launcher for `pi`: macOS uses `sandbox-exec` with SBPL, Linux uses `bwrap`. Network sandboxing is intentionally out of scope for the first iteration.

## Context

`pi` currently runs with normal user permissions and ships with tools that can read, write, edit, and execute shell commands. The first sandbox boundary should preserve normal coding-agent usefulness in repositories while reducing accidental access to secrets elsewhere in `$HOME`.

The permission model should be equivalent across OSes even though implementation details differ:

- Read/write access to `$HOME/repos`.
- Read/write access to `$HOME/.pi/agent` for simple pi settings, package, and session behavior.
- Read-only access to the minimum system and package paths required to start and run tools.
- No direct access to sensitive `$HOME` paths such as SSH keys, cloud credentials, git hosting tokens, shell history, and dotgen secrets.
- No network restrictions yet.

## Design Goals

1. Add a `pi-sandbox` launcher installed by the existing `PiAgent` component.
2. Keep the generated policy files reviewable in `dist/<env>/config/pi/sandbox/`.
3. Use one shared permission inventory rendered into OS-specific policy formats.
4. Avoid embedding secrets in generated configs.
5. Fail closed when the current working directory is outside `$HOME/repos`, unless an explicit escape hatch is added later.

## Permission Inventory

### Read/write paths

These paths should be writable on both OSes:

- `$HOME/repos`
- `$HOME/.pi/agent`, with sensitive child paths masked or denied separately.
- OS temp paths needed by child tools:
  - macOS: `$TMPDIR`, `/private/tmp`, `/private/var/tmp`
  - Linux: `/tmp`, `/var/tmp` through sandbox-private tmpfs where possible

### Read-only paths

These paths should be readable on both OSes, with OS-specific roots:

- Project context under `$HOME/repos` through the read/write rule.
- Pi global config under `$HOME/.pi/agent` through the read/write rule, after changing generated `models.json` to reference environment variable names rather than literal secret values.
- System command and library roots:
  - macOS: `/bin`, `/sbin`, `/usr/bin`, `/usr/sbin`, `/usr/lib`, `/usr/share`, `/System/Library`, `/Library`, `/opt/homebrew`, `/usr/local`.
  - Linux: `/bin`, `/sbin`, `/usr`, `/lib`, `/lib64`, `/etc`, and distribution-specific linker paths when present.
- Node/npm installation roots used by fnm:
  - `$HOME/.local/share/fnm`
  - `$HOME/.local/state/fnm_multishells`, if required by generated shell activation.

### Hidden secret paths

These paths should be denied on macOS and not mounted on Linux. Pi OAuth state is intentionally excluded from this list so OAuth-based providers can keep working through `$HOME/.pi/agent`.

- `$HOME/.config/dotgen/secrets.env`
- `$HOME/.ssh`
- `$HOME/.gnupg`
- `$HOME/.aws`
- `$HOME/.azure`
- `$HOME/.config/gcloud`
- `$HOME/.kube`
- `$HOME/.docker/config.json`
- `$HOME/.config/gh/hosts.yml`
- `$HOME/.git-credentials`
- `$HOME/.netrc`
- `$HOME/.npmrc`
- `$HOME/.pypirc`
- `$HOME/.cargo/credentials.toml`
- `$HOME/.claude`
- Shell history files such as `$HOME/.bash_history`, `$HOME/.zsh_history`, and `$HOME/.python_history`.

If a provider requires a credential, the launcher should source `$HOME/.config/dotgen/secrets.env` before entering the sandbox and pass only whitelisted environment variables into the sandbox process. Do not expose the secrets file itself.

## macOS Seatbelt Design

Create an SBPL template at `config/pi/sandbox/pi-macos.sb`. The launcher should resolve the original `pi` binary before entering the sandbox because shell aliases/functions such as `pi-unsafe` are not available inside `exec`.

```bash
sandbox-exec \
  -D HOME="$HOME" \
  -D REPOS="$HOME/repos" \
  -D PI_AGENT="$HOME/.pi/agent" \
  -D TMPDIR="${TMPDIR:-/tmp}" \
  -f "$HOME/.config/pi/sandbox/pi-macos.sb" \
  "$pi_bin" "$@"
```

Policy shape:

```scheme
(version 1)
(deny default)

(allow process*)
(allow signal)
(allow sysctl*)
(allow mach-lookup)

(allow file-read* file-write* (subpath (param "REPOS")))
(allow file-read* file-write* (subpath (param "PI_AGENT")))
(allow file-read* file-write* (subpath (param "TMPDIR")))

(allow file-read*
  (subpath "/bin")
  (subpath "/usr/bin")
  (subpath "/usr/lib")
  (subpath "/usr/share")
  (subpath "/System/Library")
  (subpath "/Library")
  (subpath "/opt/homebrew")
  (subpath "/usr/local"))

(deny file* (with no-report)
  (subpath (string-append (param "HOME") "/.ssh"))
  (subpath (string-append (param "HOME") "/.aws"))
  (subpath (string-append (param "HOME") "/.config/dotgen")))
```

The final SBPL may need additional read metadata rules for parent directories and macOS runtime files. Add those incrementally from denied-operation logs instead of broadly allowing `$HOME`.

## Linux bwrap Design

Install `bubblewrap` through the shim for Debian. Create a launcher that constructs the mount namespace rather than a static profile file.

Command shape:

```bash
bwrap \
  --unshare-user-try \
  --unshare-ipc \
  --unshare-pid \
  --die-with-parent \
  --proc /proc \
  --dev-bind /dev /dev \
  --tmpfs /tmp \
  --dir "$HOME" \
  --bind "$HOME/repos" "$HOME/repos" \
  --bind "$HOME/.pi/agent" "$HOME/.pi/agent" \
  --ro-bind-try "$HOME/.local/share/fnm" "$HOME/.local/share/fnm" \
  --ro-bind-try "$HOME/.local/state/fnm_multishells" "$HOME/.local/state/fnm_multishells" \
  --ro-bind /usr /usr \
  --ro-bind /bin /bin \
  --ro-bind-try /lib /lib \
  --ro-bind-try /lib64 /lib64 \
  --ro-bind /etc /etc \
  --setenv HOME "$HOME" \
  --chdir "$PWD" \
  "$pi_bin" "$@"
```

Because bwrap exposes mounted paths, hidden secret paths are normally omitted. `$HOME/.pi/agent` is mounted writable for settings, sessions, package metadata, and OAuth state. The launcher should use `--ro-bind-try` for optional paths and should create empty parent directories for mounted files before invoking bwrap.

Do not use `--unshare-net` in this phase.

## Secret Handling Changes

The current generated `models.json` template substitutes `GOOGLE_GENERATIVE_AI_API_KEY` into the file. That makes `$HOME/.pi/agent/models.json` sensitive and conflicts with writable sandbox exposure.

Change the generated model config to use pi's environment-variable resolution:

```json
{
  "providers": {
    "google": {
      "apiKey": "GOOGLE_GENERATIVE_AI_API_KEY"
    }
  }
}
```

Then have `pi-sandbox` source `$HOME/.config/dotgen/secrets.env` outside the sandbox and export only the whitelisted variables required by pi and configured packages, starting with:

- `GOOGLE_GENERATIVE_AI_API_KEY`
- `EXA_API_KEY`

Do not pass broad environment variables by default. Start from a controlled environment with `env -i` or bwrap `--clearenv`, then add `HOME`, `PATH`, `SHELL`, `TERM`, locale variables, and the explicit API keys.

## Component Changes

### `src/dotgen/components/pi_agent.py`

- Install `bubblewrap` on Linux environments.
- Emit:
  - `pi/sandbox/pi-sandbox.sh` with mode `0o755`.
  - `pi/sandbox/pi-macos.sb`.
  - Optionally `pi/sandbox/linux-paths.env` if path inventory grows too large for inline shell.
- Install the launcher to `$HOME/.local/bin/pi-sandbox`.
- Preserve access to the original binary through `pi-unsafe`.
- Add aliases or shell functions:
  - `pi` routes to `pi-sandbox` by default.
  - `pi-unsafe` routes to the original `pi` binary for deliberate unsandboxed use.
- Allow OAuth-based providers in sandbox mode by exposing only the required pi auth state, not broad `$HOME` credentials.
- Keep package installation and updates outside pi; do not run `pi update` as part of setup or sandbox startup.
- Change `models.json` to reference environment variable names instead of embedding values.

### Tests

- Add component tests that assert:
  - Linux setup installs `bubblewrap`.
  - macOS setup does not install `bubblewrap`.
  - Sandbox config files are emitted with expected modes.
  - Secret paths appear in deny, omit, or mask lists.
  - `models.json` contains `"apiKey": "GOOGLE_GENERATIVE_AI_API_KEY"` and not a `${...}` placeholder.
- Refresh golden snapshots after reviewing emitted bash diffs.

## Critical Files

- `src/dotgen/components/pi_agent.py`
- `src/dotgen/registry.py`
- `src/dotgen/secrets.py`
- `tests/test_components.py`
- `tests/golden/<env>/setup.sh`
- `tests/golden/<env>/alias.sh`
- `tests/golden/<env>/config/pi/sandbox/*`

## Verification

- `just test`
- `just build-all`
- `just shellcheck`
- Linux smoke test:
  - `pi-sandbox --version`
  - from `$HOME/repos/dotfiles_v2`: ask pi to read and edit a scratch file.
  - confirm `$HOME/.ssh` and `$HOME/.config/dotgen/secrets.env` are inaccessible.
- macOS smoke test:
  - `pi-sandbox --version`
  - from `$HOME/repos/dotfiles_v2`: ask pi to read and edit a scratch file.
  - inspect sandbox deny logs and add only narrow read metadata exceptions.

## Decisions

1. `pi` should be an alias or shell function for `pi-sandbox` by default.
2. `pi-unsafe` should route to the original pi binary for deliberate unsandboxed use.
3. OAuth-based providers are allowed in sandbox mode. Expose the minimum pi auth state needed for provider login and refresh flows while continuing to hide unrelated `$HOME` secrets.
4. Package installation and updates happen outside pi. The sandbox launcher should not invoke `pi update`, and generated setup should only install the pinned npm packages declared by this component.
