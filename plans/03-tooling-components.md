# Plan 03 — Cross-platform tooling components

## Context

Plans 01–02 produced a working build system and a base bundle (shell, core CLI, git, SSH, helix). This plan adds the higher-value developer tooling that's the actual point of the dotfiles: the prompt, smart cd, Kubernetes, Claude Code, language toolchains, and cloud CLIs. These are the apps the user explicitly named: kubectl, claude, starship, rust, fnm, go, python tooling, jq, ripgrep (already done in 02), GitHub setup (done in 02), GCP, AWS — plus zoxide.

Distribution by environment:

| Component | debian | fedora | macos |
|---|:-:|:-:|:-:|
| starship (+ starship.toml config) | ✓ | ✓ | ✓ |
| zoxide | ✓ | ✓ | ✓ |
| kubectl (+ helm + k9s + aliases) | ✓ | ✓ | ✓ |
| claude_code (+ ~/.claude/settings.json) | ✓ | ✓ | ✓ |
| python_tools (uv + distro build deps) | ✓ | ✓ | ✓ |
| rust (rustup) | – | ✓ | ✓ |
| node_fnm (fnm + bashrc init) | – | ✓ | ✓ |
| go_lang | – | ✓ | ✓ |
| gcloud SDK | – | ✓ | ✓ |
| aws (awscli v2 + ~/.aws/config stub) | – | ✓ | ✓ |

Debian stays minimal: prompt, navigation, kubectl, claude, python — nothing else.

## Pre-flight checks

Plan 02's foundation may have shifted. Re-verify:

```bash
cd /Users/alex/repos/dotfiles_v2
just lint && just typecheck && just test       # baseline green
ls src/dotgen/components/                      # expect: bash_base, core_utils, git_setup, github_ssh, helix
grep -l 'class .*Component' src/dotgen/components/*.py  # confirm component class naming
```

Read these to verify before writing new components:

- `src/dotgen/components/core_utils.py` — copy its dataclass shape for new components
- `src/dotgen/component.py` — confirm Protocol signature is unchanged
- `src/dotgen/fragment.py` — confirm `ConfigFile.dest` semantics
- `src/dotgen/shim.py` — confirm `add_repo`/`download_bin`/`install_config` are available; if any helper is missing, **add it to the shim before** writing a component that needs it
- `src/dotgen/environment.py` — confirm `_BASE` tuple naming and how to compose

If `add_repo` doesn't yet support a needed pattern (e.g., a distro repo that needs both a keyring file *and* a sources line), extend the shim first and update the parity test.

## Tasks

### 1. Components — shared (all envs)

#### `starship.py`

- `setup`: download starship via official installer (`curl -sS https://starship.rs/install.sh | sh -s -- -y`) gated on `bin_exists starship`. Falls back to `download_bin` from GitHub releases if needed.
- `bashrc`: `eval "$(starship init bash)"` + `set_win_title` integration is already in `bash_base`.
- `ConfigFile` `~/.config/starship.toml` built programmatically in `src/dotgen/starship_config.py`:
  - format: minimal but custom (preserve v1 layout vibe)
  - `[kubernetes]` enabled
  - **No hardcoded contexts.** A generic style rule: contexts matching `*prod*` render bold red. Construct via `[[kubernetes.contexts]]` entries with regex.
  - All other cloud/runtime modules explicitly disabled (gcloud, aws, docker_context, dotnet) to keep the prompt fast.

#### `zoxide.py`

- `setup`: `install_package zoxide` (all three OSes have it in their default repos).
- `bashrc`: `eval "$(zoxide init bash)"` guarded by `bin_exists zoxide`.

#### `kubectl.py`

- `setup`:
  - kubectl: macOS `brew install kubectl`; debian/fedora `add_repo` for the official Kubernetes repo, then `install_package kubectl`.
  - helm: `download_tar_bin helm get.helm.sh/helm-v3.16.x-...` (tar pattern from v1 setup.sh works fine), or `install_package helm` on macOS.
  - k9s: `install_package k9s` on macOS; debian/fedora download from GitHub releases via `download_tar_bin`.
- `bashrc`: `KUBECONFIG="$HOME/.kube/config"` if dir exists; source completion: `source <(kubectl completion bash)` and `source <(helm completion bash)` (guarded by `bin_exists`).
- `alias` contributions (kept generic — drop QA-Wolf-specific stuff):
  - `kc='kubectl'`, `kca='kubectl get all'`, `kcn='kubectl config use-context'`, `kcr='kubectl config current-context'`
  - functions: `pod_names()`, `k8s_secrets()`, `k8s_env()`, `k8s_events()`, `k8s_all_resources_in_ns()` from v1 `aliases` lines covering kube helpers — port verbatim, they're OS-agnostic.

#### `claude_code.py`

- `setup`: official install — `curl -fsSL https://claude.ai/install.sh | bash` gated on `bin_exists claude`. (Verify URL at implementation time.)
- `bashrc`: `source <(claude completion bash 2>/dev/null || true)`.
- `ConfigFile` `~/.claude/settings.json`:
  - `{"includeCoAuthoredBy": false}` plus any lightweight defaults.
  - **Drop** the v1 `ENABLE_CLAUDEAI_MCP_SERVERS=false` env var — outdated.

#### `python_tools.py`

- `setup`:
  - `install_package` per-distro build deps: debian `build-essential libssl-dev libffi-dev`, fedora `gcc gcc-c++ openssl-devel libffi-devel`, macos: nothing (Xcode CLT assumed).
  - Install `uv` via `curl -LsSf https://astral.sh/uv/install.sh | sh` if `bin_exists uv` is false.
- `bashrc`: prepend `~/.local/bin` to PATH (already in base header — keep idempotent), source `~/.local/bin/env` if present (uv emits this).

### 2. Components — fedora + macos only

#### `rust.py`

- `setup`: `curl https://sh.rustup.rs -sSf | sh -s -- -y --default-toolchain stable`, gated on `bin_exists cargo`.
- `bashrc`: `[ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env"`.

#### `node_fnm.py`

- `setup`: `curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell`, gated on `bin_exists fnm`.
- `bashrc`: `eval "$(fnm env --use-on-cd)"` guarded by `bin_exists fnm`.

#### `go_lang.py`

- `setup`: macOS `brew install go`; fedora `install_package golang`. (Drop v1's manual tar download — packages are recent enough.)
- `bashrc`: `export GOPATH="$HOME/go"`, prepend `$GOPATH/bin` to PATH.

#### `gcloud.py`

- `setup`:
  - macOS: `brew install --cask google-cloud-sdk`
  - fedora: `add_repo dnf google-cloud-sdk https://packages.cloud.google.com/yum/repos/cloud-sdk-el9-x86_64`, then `install_package google-cloud-cli`
- `bashrc`: source `path.bash.inc` and `completion.bash.inc` from the SDK (paths differ by OS — guard with `[ -f ... ]`).

#### `aws.py`

- `setup`:
  - macOS: `brew install awscli`
  - fedora: `download_bin awscli https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip` + unzip + `./aws/install`. (Architecture detection via `detect_arch`.)
- `bashrc`: `complete -C "$(command -v aws_completer)" aws` if `bin_exists aws_completer`.
- `ConfigFile` `~/.aws/config` (mode 0o600):
  ```
  # Populate per-profile settings via `aws configure --profile <name>`.
  # Generated stub — do not commit credentials here.
  [default]
  region = us-east-1
  output = json
  ```

### 3. Wire ENVIRONMENTS

```python
_SHARED = _BASE + (Starship(), Zoxide(), Kubectl(), ClaudeCode(), PythonTools())
_FULL_ADDONS = (Rust(), NodeFnm(), GoLang(), Gcloud(), Aws())

ENVIRONMENTS = {
    "debian": Environment("debian", OS.DEBIAN, PkgMgr.APT, components=_SHARED),
    "fedora": Environment("fedora", OS.FEDORA, PkgMgr.DNF, components=_SHARED + _FULL_ADDONS),
    "macos":  Environment("macos",  OS.MACOS,  PkgMgr.BREW, components=_SHARED + _FULL_ADDONS),
}
```

### 4. Tests

- Per-component unit tests asserting fragment shape (e.g., starship emits a `ConfigFile` with `dest='~/.config/starship.toml'`).
- Update `test_render_snapshot.py` golden files (run with `UPDATE_GOLDEN=1`) and review the diff carefully.
- Add `test_shellcheck.py` (subprocess `shellcheck`, `pytest.skip` if not installed). `just ci` requires it.
- Bash parity: `bash -n` on every generated file (already tested in Plan 01; just rerun).

## Critical files

- `/Users/alex/repos/dotfiles_v2/src/dotgen/components/{starship,zoxide,kubectl,claude_code,python_tools,rust,node_fnm,go_lang,gcloud,aws}.py`
- `/Users/alex/repos/dotfiles_v2/src/dotgen/starship_config.py`
- `/Users/alex/repos/dotfiles_v2/src/dotgen/environment.py`
- `/Users/alex/repos/dotfiles_v2/tests/test_render_snapshot.py` (regenerate goldens)
- `/Users/alex/repos/dotfiles_v2/tests/test_shellcheck.py`

## Verification

```bash
cd /Users/alex/repos/dotfiles_v2
just lint && just typecheck && just test
just build-all && just shellcheck

# macOS smoke install:
bash dist/macos/setup.sh
exec bash -l
for cmd in starship zoxide kubectl helm k9s claude uv cargo fnm go gcloud aws; do
  command -v "$cmd" >/dev/null && echo "OK $cmd" || echo "MISSING $cmd"
done
test -f ~/.config/starship.toml
test -f ~/.claude/settings.json
test -f ~/.aws/config

# Linux smoke (debian VM, scp dist/debian/ over):
bash setup.sh
for cmd in starship zoxide kubectl claude uv; do command -v "$cmd"; done
# (no rust/go/fnm/gcloud/aws on debian by design)
```
