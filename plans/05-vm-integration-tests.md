> **Superseded — fedora removed in Plan 07.**

# Plan 05 — VM-based integration tests via OrbStack

## Context

Plans 01–04 took the system as far as static guarantees go: `just ci` validates the *generated bash* via lint, typecheck, unit tests, snapshot diffs against `tests/golden/<env>/`, and `shellcheck` on the emitted scripts. None of it actually runs `setup.sh` against a clean machine, so regressions only show up the next time someone bootstraps a real box — a missing DNF package on Fedora, a stale `add_repo` URL, a non-idempotent `>>` write to `~/.bashrc`.

OrbStack runs full Linux VMs on macOS via `Virtualization.framework`, fast enough to be practical (boot ~10s, end-to-end per env ~3–7 min) and scriptable through `orb create / orb -m / orb push / orb delete`. This plan adds opt-in VM tests for the two Linux envs (`debian`, `fedora`); `macos` is the host and out of scope.

Design choices:

- **pytest-backed**, fixture-driven, gated behind a `vm` marker. Reuses existing test infra; failures report per-assertion.
- **Always teardown**, with a `KEEP_VM=1` escape hatch for forensics.
- **NOT in `just ci`** — runs via a separate `just test-vm` recipe so CI stays fast.

## Pre-flight

1. OrbStack installed: `command -v orb` (else `brew install orbstack`).
2. Confirm distro tags currently accepted by OrbStack — docs show `debian:bookworm` and `fedora` (latest). Validate at implementation time:
   ```bash
   orb create debian:bookworm _probe-deb && orb delete _probe-deb
   orb create fedora           _probe-fed && orb delete _probe-fed
   ```
   If a tag has shifted, update the `IMAGES` map in `dotgen.vm`.
3. `just build-all` succeeds locally (the fixture builds its own copy too, but a clean baseline rules out drift).
4. No leftover test VMs: `orb list | grep dotgen-test-` should be empty.

## Tasks

### 1. `src/dotgen/vm.py` — thin `orb` wrapper

One frozen dataclass + one context manager. No state beyond the VM name.

```python
@dataclass(frozen=True)
class VmHandle:
    name: str
    user: str   # OrbStack uses the macOS username on the guest

    def run(self, cmd: str, *, login: bool = False, check: bool = True) -> subprocess.CompletedProcess: ...
    def push(self, src: Path, dest: str) -> None: ...
    def assert_cmd(self, cmd: str, *, login: bool = False) -> None: ...

@contextmanager
def vm_session(env_name: str, image: str) -> Iterator[VmHandle]: ...
```

- `run` → `orb -m <name> -u <user> bash {-lc | -c} <cmd>`. `login=True` triggers a login shell so `~/.bashrc` is sourced — needed for alias / function assertions.
- `push` → `orb push -m <name> <src> <dest>`.
- `vm_session` creates `dotgen-test-<env>-<uid8>` (parallel-safe), yields the handle, and on exit runs `orb delete` unless `os.environ.get("KEEP_VM") == "1"`.
- `assert_cmd` runs the command with `check=False` and raises `AssertionError(...)` including stdout/stderr on non-zero — pytest renders this cleanly.

### 2. `tests/test_vm_integration.py` — fixture + assertions

```python
pytestmark = pytest.mark.vm

IMAGES = {"debian": "debian:bookworm", "fedora": "fedora"}

@pytest.fixture(scope="module", params=["debian", "fedora"])
def vm(request, tmp_path_factory):
    env_name = request.param
    work = tmp_path_factory.mktemp(f"vm-{env_name}")
    build_env(ENVIRONMENTS[env_name], work / env_name)        # fresh build, not stale dist/
    tar = shutil.make_archive(str(work / env_name), "gztar", root_dir=work, base_dir=env_name)
    with vm_session(env_name, IMAGES[env_name]) as handle:
        handle.push(Path(tar), "/tmp/dotgen.tar.gz")
        handle.run("mkdir -p /tmp/dotgen && tar xzf /tmp/dotgen.tar.gz -C /tmp/dotgen")
        handle.run(f"bash /tmp/dotgen/{env_name}/setup.sh deploy")
        yield (env_name, handle)
```

One assertion per `def test_*` so failures are reported individually. Representative set:

| Concern | Assertion |
|---|---|
| Core utils (all envs) | `command -v jq && command -v rg && command -v fd && command -v tree && command -v htop` |
| Tooling (all envs) | `command -v kubectl && command -v helm && command -v starship && command -v zoxide && command -v uv && command -v gh && command -v claude` |
| Helix | `command -v hx && [ -f ~/.config/helix/config.toml ]` |
| Git config | `grep -q 'editor = hx' ~/.gitconfig` |
| Bashrc / aliases (login shell) | `bash -lc 'echo $EDITOR'` → `hx`; `bash -lc 'type kc'` reports a function |
| Fedora-only addons | `command -v cargo && command -v fnm && command -v go && command -v aws && command -v zed`; skip on debian via `pytest.skipif` |
| **Idempotency** | re-run `setup.sh deploy`; assert exit 0 *and* `~/.bashrc` is byte-identical to the post-first-run snapshot (`sha256sum` taken before/after) |

The idempotency check is the highest-value assertion — it's the invariant CLAUDE.md calls out and is the one most likely to silently regress.

### 3. `pyproject.toml` — register marker, default-exclude

```toml
[tool.pytest.ini_options]
markers = ["vm: integration test that boots an OrbStack VM (slow, opt-in)"]
addopts = "-m 'not vm'"
```

Keeps `just test` and `just ci` unchanged in scope and runtime.

### 4. `justfile` — recipes

```
test-vm env="debian":
    uv run pytest tests/test_vm_integration.py -v -m vm -k {{env}}

test-vm-all:
    uv run pytest tests/test_vm_integration.py -v -m vm
```

`just ci` is **not** modified.

## Critical files

New:
- `src/dotgen/vm.py`
- `tests/test_vm_integration.py`

Modified:
- `pyproject.toml` (marker + default exclude)
- `justfile` (`test-vm`, `test-vm-all`)

Existing code reused (no edits):
- `src/dotgen/render.py::build_env` — fixture builds a fresh tree per module (avoids depending on `dist/` state).
- `src/dotgen/environment.py::ENVIRONMENTS` — single source of truth for env list.
- `dist/<env>/setup.sh` `deploy` mode — what runs on the guest.

## Verification

```bash
just build-all                       # baseline
just test-vm debian                  # ~3–5 min
just test-vm fedora                  # ~5–7 min (full addons)
just test-vm-all
orb list                             # must be empty after clean runs
KEEP_VM=1 just test-vm debian        # then: ssh dotgen-test-debian-<uid>@orb
just ci                              # must remain green; runtime unchanged (vm marker excluded)
```

Spot-check the failure paths during implementation:

- Drop `kubectl` from `_SHARED` temporarily → `test_kubectl_in_path` fails on both envs; revert.
- Add an unguarded `echo X >> ~/.bashrc` to a component → idempotency assertion fails (sha mismatch); revert.
- `KEEP_VM=1` actually leaves the VM around (`orb list` shows it) and an `orb delete` cleans up.
