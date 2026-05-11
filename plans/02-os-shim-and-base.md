> **Superseded — fedora removed in Plan 07.**

# Plan 02 — OS shim implementation & foundational components

## Context

Plan 01 stood up the skeleton: package layout, dataclasses, renderer, stub OS shim with all function names. This plan fills in the shim bodies for all three OSes and adds the components that every environment shares: shell base config, core CLI utilities, git config, GitHub SSH setup, and Helix (default editor).

After this plan, `dist/<env>/setup.sh` should be runnable end-to-end on a fresh box and produce a usable shell with `jq`, `rg`, `fd`, `vim`, git pre-configured, an SSH key, and `hx` as the default editor. Higher-level tooling (kubectl, claude, starship, languages, cloud CLIs) lands in Plan 03.

## Pre-flight checks

Plan 01 may have shifted things. Confirm:

```bash
cd /Users/alex/repos/dotfiles_v2
test -f pyproject.toml justfile
just typecheck && just test                 # baseline green
ls src/dotgen/                              # expect: types.py fragment.py component.py environment.py shim.py render.py bash.py cli.py components/
just build-all && ls dist/macos/            # expect: setup.sh alias.sh .bashrc os_shim.sh
grep -E '^[a-z_]+\(\)' dist/macos/os_shim.sh | sort   # confirm full stub function list present
```

Read these to confirm signatures/locations before editing:

- `src/dotgen/shim.py` — confirm `OSShim` class shape
- `src/dotgen/component.py` — confirm `Component` protocol
- `src/dotgen/fragment.py` — confirm `Fragment` and `ConfigFile`
- `src/dotgen/environment.py` — confirm `ENVIRONMENTS` dict and how to wire `components=(...)`
- `src/dotgen/render.py` — confirm fragment merging order and config-file write path

If any of these have moved or been renamed, update this plan's path references before proceeding.

## Tasks

### 1. Implement `os_shim.sh` per OS in `shim.py`

For each of `OS.DEBIAN`, `OS.FEDORA`, `OS.MACOS`, fill the shim function bodies. Keep the function set identical across OSes (parity test from Plan 03 onward will enforce this).

Per-OS body sketch:

| function | debian | fedora | macos |
|---|---|---|---|
| `detect_os` | `echo debian` | `echo fedora` | `echo macos` |
| `detect_arch` | `uname -m` | `uname -m` | `uname -m` |
| `bin_exists` | `command -v "$1" >/dev/null` | same | same |
| `pkg_installed` | `dpkg -s "$1" >/dev/null 2>&1` | `rpm -q "$1" >/dev/null 2>&1` | `brew list --versions "$1" >/dev/null 2>&1` |
| `install_package` | `pkg_installed "$1" \|\| sudo apt-get install -y "$1"` | `... sudo dnf install -y ...` | `... brew install ...` |
| `install_packages` | iterates `install_package` | same | same |
| `add_repo` | `apt`: writes `/etc/apt/sources.list.d/<id>.list` + keyring; `tap`/`dnf` cases error | `dnf`: drops `/etc/yum.repos.d/<id>.repo` from URL; others error | `tap`: `brew tap "$id" "$url"`; others error |
| `update_pkg_index` | `sudo apt-get update -y` | `sudo dnf -y check-update \|\| true` | `brew update` |
| `service_enable` | `sudo systemctl enable --now "$1"` | same | no-op (`return 0`) |
| `download_bin` | `curl -sSL "$2" -o "$HOME/bin/$1" && chmod +x "$HOME/bin/$1"` | same | same |
| `download_tar_bin` | curl + `tar -xzO` of `$2` into `$HOME/bin/$1` | same | same |
| `link_file` / `ensure_dir` / `install_config` | `mkdir -p`, `cp`, `chmod` (idempotent) | same | same |
| `log` / `error` / `ask` | colored `printf` to stderr | same | same |

Implementation note: keep each shim as a single Python string constant in `shim.py` per OS (`_SHIM_DEBIAN`, `_SHIM_FEDORA`, `_SHIM_MACOS`). `OSShim(os).render()` looks up the right one and prepends a header. No templating.

### 2. Foundational components

Each lives under `src/dotgen/components/`. Each is a `@dataclass(frozen=True)` implementing `Component`. All apply to all three envs unless noted.

#### `bash_base.py`

- `bashrc` contributions: `HISTSIZE=1000000`, `HISTFILESIZE=1000000`, `HISTCONTROL=ignoredups:erasedups`, `shopt -s histappend`, `ulimit -n 65536`.
- `bashrc`: `set_win_title` function, `PROMPT_COMMAND="set_win_title; $PROMPT_COMMAND"`.
- `bashrc`: `epoch()` function (Python one-liner converting Unix ts → readable).
- `alias`: generic aliases — `l='ls -hlAG'` (macOS) / `l='ls -hlA --color=auto'` (linux), `klear='clear && printf "[3J"'`, `rgc='rg -C 30'`, `ip='curl -s ifconfig.me'`, git aliases (`gs`, `gc`, `ga`, `gpo`, `gpfo`, `gl` with the colored log format from v1 line 1–60 of `aliases`).

Per-OS `l` alias is the only branch.

#### `core_utils.py`

`install_packages` call with per-OS list:

| | debian | fedora | macos |
|---|---|---|---|
| jq | jq | jq | jq |
| ripgrep | ripgrep | ripgrep | ripgrep |
| fd | fd-find (+ symlink `~/bin/fd → fdfind`) | fd-find | fd |
| tree | tree | tree | tree |
| vim | vim | vim | vim |
| htop | htop | htop | htop |
| gnupg | gnupg2 | gnupg2 | gnupg |
| bash-completion | bash-completion | bash-completion | bash-completion |

#### `git_setup.py`

Emits two `ConfigFile`s:

- `~/.gitconfig` — `user.name=Alex Angelini`, `user.email=alex.louis.angelini@gmail.com`, `core.editor=hx`, `core.excludesFile=~/.gitignore_global`, `push.default=current`, `diff.algorithm=patience`, `init.defaultBranch=main`, `url."ssh://git@github.com/".insteadOf=https://github.com/`, `pull.ff=only`.
- `~/.gitignore_global` — `.DS_Store`, `__scratch__.*`, `CLAUDE.md`, `.serena/`, `.node-version` (we use fnm + `.node-version`), `node_modules/` (caller asked), keep minimal.

Emits no `setup` text beyond `install_config config/git/gitconfig "$HOME/.gitconfig"` (called via shim helper).

#### `github_ssh.py`

`setup` block: if `~/.ssh/id_ed25519` missing, run `ssh-keygen -t ed25519 -a 100 -N "" -C "$(detect_os)-$(hostname)" -f ~/.ssh/id_ed25519`. Adds `github.com` to `~/.ssh/known_hosts` via `ssh-keyscan`. Starts ssh-agent on macOS. Echoes the public key with a `log` instructing the user to paste it into GitHub.

#### `helix.py`

- `setup`: `install_package helix` (debian: `helix` via PPA — fall back to a downloaded release tarball; fedora: COPR; macos: `brew install helix`). Recommended: ship a small `add_repo` call where needed and rely on package mgr otherwise. If a distro has no first-party package, use `download_tar_bin`.
- `bashrc`: `export EDITOR=hx` and `export VISUAL=hx`.
- `ConfigFile` `~/.config/helix/config.toml` — minimal: `theme = "default"`, `editor.line-number = "relative"`, `editor.cursor-shape.insert = "bar"`.

### 3. Wire components into ENVIRONMENTS

`environment.py`:

```python
from .components import bash_base, core_utils, git_setup, github_ssh, helix

_BASE = (bash_base.BashBase(), core_utils.CoreUtils(), git_setup.GitSetup(),
         github_ssh.GitHubSsh(), helix.Helix())

ENVIRONMENTS = {
    "debian": Environment("debian", OS.DEBIAN, PkgMgr.APT, components=_BASE),
    "fedora": Environment("fedora", OS.FEDORA, PkgMgr.DNF, components=_BASE),
    "macos":  Environment("macos",  OS.MACOS,  PkgMgr.BREW, components=_BASE),
}
```

(Plan 03 will extend each tuple with env-specific components.)

### 4. Tests

- `tests/test_shim.py` — for each OS, parse shim with regex `^[a-z_][a-z_0-9]*\(\)` and assert the function name set is identical across OSes. Run `bash -n` on each shim.
- `tests/test_components.py` — instantiate each component, assert `render()` returns a `Fragment`. For `git_setup`, assert two ConfigFiles with expected `dest`. For `core_utils`, assert per-OS package list contains the right `fd-find` vs `fd` token.
- `tests/test_render_snapshot.py` — golden snapshots for all four output files per env, stored under `tests/golden/<env>/`. Re-run with `UPDATE_GOLDEN=1` to refresh after intentional changes.

### 5. Add `shellcheck` recipe to justfile

```
shellcheck:     shellcheck dist/*/*.sh dist/*/.bashrc
```

Make `just ci` chain include it.

## Critical files

- `/Users/alex/repos/dotfiles_v2/src/dotgen/shim.py`
- `/Users/alex/repos/dotfiles_v2/src/dotgen/components/{bash_base,core_utils,git_setup,github_ssh,helix}.py`
- `/Users/alex/repos/dotfiles_v2/src/dotgen/environment.py`
- `/Users/alex/repos/dotfiles_v2/tests/{test_shim,test_components,test_render_snapshot}.py`
- `/Users/alex/repos/dotfiles_v2/tests/golden/{debian,fedora,macos}/`
- `/Users/alex/repos/dotfiles_v2/justfile`

## Verification

```bash
cd /Users/alex/repos/dotfiles_v2
just lint && just typecheck && just test
just build-all
just shellcheck                                 # passes on every emitted file
for f in dist/*/*.sh dist/*/.bashrc; do bash -n "$f"; done

# macOS smoke (local box):
bash dist/macos/setup.sh
exec bash -l
which jq rg fd hx vim                           # all present
git config user.email                           # alex.louis.angelini@gmail.com
test -f ~/.ssh/id_ed25519
echo $EDITOR                                    # hx
```

If macOS host already has these tools (likely true), confirm idempotency: re-running the script makes no destructive changes and exits 0.
