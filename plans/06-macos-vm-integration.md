> **Superseded — fedora removed in Plan 07.**

# Plan 06 — macOS VM integration tests via tart (unified backend)

## Context

Plan 05 added OrbStack-VM integration tests for the two Linux envs (`debian`, `fedora`), leaving `macos` — the heaviest env (`_BASE + _SHARED + _FULL_ADDONS + Ghostty + _LAST`) — verified only by snapshot diff against `tests/golden/macos/` and `shellcheck`. Nothing actually runs `dist/macos/setup.sh deploy` end-to-end, so cask renames, tap drift, and idempotency regressions in macOS-touched components only surface the next time someone bootstraps a real Mac.

[tart](https://tart.run) ([cirruslabs/tart](https://github.com/cirruslabs/tart)) runs full macOS guests on Apple Silicon via `Virtualization.framework`, distributed as OCI images on `ghcr.io`. It's the macOS analogue of OrbStack with a similar lifecycle: `tart pull / clone / run / ip / stop / delete`. End-to-end deploy is ~15–25 min — cask installs (`zed`, `ghostty`, `google-cloud-sdk`) dominate.

This plan **does not** add a parallel module/test file. Instead it refactors `src/dotgen/vm.py` to factor the OrbStack-specific bits behind a small `VmBackend` protocol and adds a `TartBackend` alongside, then extends the existing fixture in `tests/test_vm_integration.py` to a third env. One marker (`vm`), one test file, one source of truth for the assertion set.

Design choices:

- **One `VmBackend` protocol, two impls (`_OrbBackend`, `_TartBackend`)**. Backend selection is per-env (`macos → tart`, else `orb`) inside `vm_session`. `VmHandle` carries a backend reference and dispatches to it. Keeps `VmCommandError`/`_stream_block` shared.
- **Skip-on-unavailable, not fail**. Each backend has an `is_available() -> (bool, reason)` probe (Apple Silicon + `tart` + `sshpass` for tart; `orb` for orb). The fixture skips with a clear reason rather than erroring. Lets `just test-vm-all` work cleanly on a Linux dev box (skips macos) and on an Apple Silicon dev box (runs all three).
- **Image: `ghcr.io/cirruslabs/macos-sequoia-base` (base variant)** — Homebrew is preinstalled, no Xcode (~30 GB). `vanilla` lacks brew; `xcode`/`runner` are unnecessarily large (~80 GB+). `dist/macos/setup.sh`'s opening `brew update` works out of the box.
- **Image is digest-pinned, not `:latest`.** A single constant `MACOS_IMAGE = "ghcr.io/cirruslabs/macos-sequoia-base@sha256:<digest>"` lives at the top of `tests/test_vm_integration.py`. The local OCI cache is the source of truth — once `tart pull <pinned-ref>` has populated it, no test run will ever trigger a remote fetch (digest refs are immutable). Bumping the pin is an explicit, reviewable PR.
- **Fail-fast cache guard.** Before `tart clone`, the fixture checks the local OCI cache (`~/.tart/cache/OCIs/<host>/<repo>/sha256:<digest>/`) for the pinned digest and aborts with `VmBackendUnavailable("run \`tart pull <ref>\` first (~30 GB)")` if missing. Belt-and-suspenders against any future tart-version regression that re-pulls on `clone`.
- **SSH transport**: `sshpass -p admin ssh admin@<ip>`. cirruslabs images use `admin`/`admin` by convention. Stateless — no key injection or first-boot keygen wait.
- **Always teardown**, with `KEEP_VM=1` escape hatch. Same contract as Plan 05.
- **NOT in `just ci`**. Same as Plan 05.

## Pre-flight

1. `just build-all` succeeds locally (the fixture rebuilds, but a clean baseline rules out drift).
2. Apple Silicon host for the macos leg: `[ "$(uname -m)" = "arm64" ]`. The fixture skips macos automatically on x86_64; the check is just so you know why.
3. tart installed: `command -v tart` (else `brew install cirruslabs/cli/tart`).
4. sshpass installed: `command -v sshpass` (else `brew install hudochenkov/sshpass/sshpass`).
5. Pinned image pre-pulled (one-time, ~30 GB). The pin lives in `tests/test_vm_integration.py` as `MACOS_IMAGE`:
   ```bash
   pin=$(rg -No 'MACOS_IMAGE\s*=\s*"([^"]+)"' -r '$1' tests/test_vm_integration.py)
   tart pull "$pin"
   ```
   The pin is a digest ref (`...@sha256:<digest>`), so this is a no-op if the cache already has it. Disk-usage: tart clones are CoW against the cached image, but `brew install` writes grow each clone — budget ~10 GB headroom per concurrent VM.

   **To refresh the pin** (e.g. macOS point release): `tart pull ghcr.io/cirruslabs/macos-sequoia-base:latest`, run `tart fqn ghcr.io/cirruslabs/macos-sequoia-base:latest` (or `crane digest`) to capture the immutable digest, update `MACOS_IMAGE` in the test file, run `just test-vm macos` to validate, commit. Never let `:latest` reach the test code.
6. No leftover test VMs:
   ```bash
   orb list  | grep dotgen-test- || true
   tart list | grep dotgen-test- || true
   ```
   Both should be empty.
7. Host macOS 14+ (Sequoia guest images require it).

## Tasks

### 1. Refactor `src/dotgen/vm.py` — introduce `VmBackend` protocol

Goal: leave the public surface (`VmHandle`, `VmCommandError`, `vm_session`) compatible with `tests/test_vm_integration.py`, but route the orb-specific calls through an `_OrbBackend`. Internal-only — backend classes are underscored.

Sketch (only the new parts; existing `VmCommandError` / `_stream_block` / `_as_text` unchanged):

```python
class VmBackendUnavailable(RuntimeError):
    """Raised when a backend's required tooling/host is missing — fixture skips."""

class _VmBackend(Protocol):
    label: str
    def is_available(self) -> tuple[bool, str]: ...
    def create(self, vm_name: str, image: str) -> str: ...   # returns guest username
    def run(self, vm_name: str, user: str, cmd: str, *,
            login: bool, timeout: float | None) -> subprocess.CompletedProcess[str]: ...
    def push(self, vm_name: str, user: str, src: Path, dest: str) -> None: ...
    def teardown(self, vm_name: str) -> None: ...

class _OrbBackend:
    label = "orbstack"
    def is_available(self) -> tuple[bool, str]:
        return (True, "") if shutil.which("orb") else (False, "orb not on PATH")
    def create(self, vm_name, image):
        subprocess.run(["orb", "create", image, vm_name], capture_output=True, text=True, check=True)
        return os.environ["USER"]
    def run(self, vm_name, user, cmd, *, login, timeout):
        flag = "-lc" if login else "-c"
        return subprocess.run(
            ["orb", "-m", vm_name, "-u", user, "bash", flag, cmd],
            capture_output=True, text=True, check=False, timeout=timeout,
        )
    def push(self, vm_name, _user, src, dest):
        subprocess.run(["orb", "push", "-m", vm_name, str(src), dest],
                       capture_output=True, text=True, check=True)
    def teardown(self, vm_name):
        subprocess.run(["orb", "delete", "-f", vm_name],
                       capture_output=True, text=True, check=False)


@dataclass
class _TartSession:
    popen: subprocess.Popen[bytes]
    ip: str

_SSH_OPTS = (
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=5",
)

class _TartBackend:
    label = "tart"
    _SSH_USER = "admin"
    _SSH_PASS = "admin"
    def __init__(self) -> None:
        self._sessions: dict[str, _TartSession] = {}
    def is_available(self) -> tuple[bool, str]:
        if platform.machine() != "arm64":
            return False, "tart requires Apple Silicon"
        for tool in ("tart", "sshpass"):
            if shutil.which(tool) is None:
                return False, f"{tool} not on PATH"
        return True, ""
    def create(self, vm_name, image):
        _ensure_tart_image_cached(image)   # fail-fast: never silently pull ~30 GB
        subprocess.run(["tart", "clone", image, vm_name],
                       capture_output=True, text=True, check=True)
        popen = subprocess.Popen(
            ["tart", "run", "--no-graphics", vm_name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ip = self._wait_for_ip(vm_name, timeout=120)
        self._wait_for_ssh(ip, timeout=120)
        self._sessions[vm_name] = _TartSession(popen=popen, ip=ip)
        return self._SSH_USER
    def run(self, vm_name, user, cmd, *, login, timeout):
        ip = self._sessions[vm_name].ip
        flag = "-lc" if login else "-c"
        argv = ["sshpass", "-p", self._SSH_PASS, "ssh", *_SSH_OPTS,
                f"{user}@{ip}", "bash", flag, shlex.quote(cmd)]
        return subprocess.run(argv, capture_output=True, text=True,
                              check=False, timeout=timeout)
    def push(self, vm_name, user, src, dest):
        ip = self._sessions[vm_name].ip
        argv = ["sshpass", "-p", self._SSH_PASS, "scp", *_SSH_OPTS,
                str(src), f"{user}@{ip}:{dest}"]
        subprocess.run(argv, capture_output=True, text=True, check=True)
    def teardown(self, vm_name):
        sess = self._sessions.pop(vm_name, None)
        if sess is not None:
            sess.popen.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                sess.popen.wait(timeout=10)
        subprocess.run(["tart", "stop", vm_name], capture_output=True, text=True, check=False)
        subprocess.run(["tart", "delete", vm_name], capture_output=True, text=True, check=False)
    def _wait_for_ip(self, name, *, timeout): ...   # poll `tart ip <name>` every 2s
    def _wait_for_ssh(self, ip, *, timeout): ...    # poll `sshpass ... ssh ... true` every 2s


def _ensure_tart_image_cached(image: str) -> None:
    """Refuse to silently pull a multi-GB image during a test run.

    tart's local OCI cache layout is ~/.tart/cache/OCIs/<host>/<repo>/<ref>/
    where <ref> is either a tag or `sha256:<digest>`. We require digest pinning
    (the convention enforced in tests/test_vm_integration.py via MACOS_IMAGE)
    and check the cache for that exact digest path. Tag refs are rejected
    here — they're moving targets and defeat the cache guarantee.
    """
    if "@sha256:" not in image:
        raise VmBackendUnavailable(
            f"tart image must be digest-pinned (got {image!r}); "
            f"see plans/06-macos-vm-integration.md for the bump procedure"
        )
    host_repo, digest = image.split("@", 1)   # digest = "sha256:<hex>"
    cache = Path.home() / ".tart" / "cache" / "OCIs" / host_repo / digest
    if not cache.exists():
        raise VmBackendUnavailable(
            f"tart image {image} not in local cache; "
            f"run `tart pull {image}` first (~30 GB, one-time)"
        )
```

Updated `VmHandle` (still frozen, now carries the backend):

```python
@dataclass(frozen=True)
class VmHandle:
    name: str
    user: str
    backend: _VmBackend
    def run(self, cmd, *, login=False, check=True, timeout=None):
        result = self.backend.run(self.name, self.user, cmd, login=login, timeout=timeout)
        if check and result.returncode != 0:
            raise VmCommandError(vm=self.name, cmd=cmd, returncode=result.returncode,
                                 stdout=result.stdout, stderr=result.stderr, login=login)
        return result
    def push(self, src, dest):
        self.backend.push(self.name, self.user, src, dest)
    def assert_cmd(self, cmd, *, login=False):
        self.run(cmd, login=login, check=True)
```

The `subprocess.TimeoutExpired` path (currently raised inside `VmHandle.run` and converted to `VmCommandError`) stays in `VmHandle.run` — wrap the backend call in a try/except so the error path is identical for both backends.

Updated `vm_session`:

```python
_BACKENDS_BY_ENV: dict[str, type[_VmBackend]] = {
    "debian": _OrbBackend,
    "fedora": _OrbBackend,
    "macos":  _TartBackend,
}

@contextmanager
def vm_session(env_name: str, image: str) -> Iterator[VmHandle]:
    backend = _BACKENDS_BY_ENV[env_name]()
    ok, reason = backend.is_available()
    if not ok:
        raise VmBackendUnavailable(f"{env_name} backend ({backend.label}) unavailable: {reason}")
    vm_name = f"dotgen-test-{env_name}-{secrets.token_hex(4)}"
    user = backend.create(vm_name, image)
    try:
        yield VmHandle(name=vm_name, user=user, backend=backend)
    finally:
        if os.environ.get("KEEP_VM") != "1":
            backend.teardown(vm_name)
```

Imports added: `platform`, `shlex`, `shutil`, `contextlib`, `typing.Protocol`.

### 2. Extend `tests/test_vm_integration.py`

Three deltas, no new file:

**a. Add macos to `IMAGES` (digest-pinned) and skip-on-unavailable.**

```python
# Digest-pinned. Bump procedure documented in plans/06-macos-vm-integration.md.
# Refresh: `tart pull ghcr.io/cirruslabs/macos-sequoia-base:latest`,
#          capture digest via `tart fqn` (or `crane digest`), update below.
MACOS_IMAGE = "ghcr.io/cirruslabs/macos-sequoia-base@sha256:REPLACE_WITH_REAL_DIGEST"

IMAGES = {
    "debian": "debian:trixie",
    "fedora": "fedora:43",
    "macos":  MACOS_IMAGE,
}

@pytest.fixture(scope="module", params=list(IMAGES))
def vm(request, tmp_path_factory) -> Iterator[tuple[str, VmHandle]]:
    env_name: str = request.param
    work = tmp_path_factory.mktemp(f"vm-{env_name}")
    build_env(ENVIRONMENTS[env_name], work / env_name)
    tar_base = str(work / env_name)
    tar = shutil.make_archive(tar_base, "gztar", root_dir=str(work), base_dir=env_name)

    deploy_timeout = 1800 if env_name == "macos" else 900
    deploy_prefix = (
        'eval "$(/opt/homebrew/bin/brew shellenv)" && ' if env_name == "macos" else ""
    )
    try:
        with vm_session(env_name, IMAGES[env_name]) as handle:
            handle.push(Path(tar), "/tmp/dotgen.tar.gz")
            handle.run("mkdir -p /tmp/dotgen && tar xzf /tmp/dotgen.tar.gz -C /tmp/dotgen")
            handle.run(f"{deploy_prefix}bash /tmp/dotgen/{env_name}/setup.sh deploy",
                       timeout=deploy_timeout)
            yield env_name, handle
    except VmBackendUnavailable as e:
        pytest.skip(str(e))
```

The `eval brew shellenv` prefix is needed because `setup.sh` runs under non-login bash on macOS. cirruslabs images put `/opt/homebrew/bin` on PATH only via `/etc/zprofile` (zsh login shell). Without the prefix, `brew update` at the top of `os_shim.sh` fails.

**b. Generalize `test_fedora_full_addons` → `test_full_addons`.** Both `fedora` and `macos` get the full addon set; only `debian` skips:

```python
def test_full_addons(vm):
    env_name, handle = vm
    if env_name == "debian":
        pytest.skip("debian env does not include full addons")
    handle.assert_cmd(
        "command -v cargo && command -v fnm && command -v go && "
        "command -v aws && command -v gcloud && command -v zed",
        login=True,   # so brew shellenv loads on macos via bash -lc
    )
```

`gcloud` is added (was missing from Plan 05's assertion). Use `login=True` to dodge per-env PATH plumbing.

**c. Add `test_ghostty_app_installed` (macos-only).**

```python
def test_ghostty_app_installed(vm):
    env_name, handle = vm
    if env_name != "macos":
        pytest.skip("Ghostty is only included on macos")
    handle.assert_cmd('[ -d "/Applications/Ghostty.app" ]')
```

**d. Existing assertions** extend to macos. Any assertion hitting a brew-installed binary needs `login=True` so PATH includes `/opt/homebrew/bin` on macos:

- `test_core_utils_installed`, `test_shared_tooling_installed`, `test_helix_installed`: add `login=True`.
- `test_git_config_uses_helix`: pure file check, no PATH dependency, leave as-is.
- `test_login_shell_sets_editor_to_hx`, `test_login_shell_loads_kubectl_alias`: already `login=True`.
- `test_setup_is_idempotent`: re-run uses the same `deploy_prefix` from the fixture — lift to a module-level helper `_deploy_cmd(env_name) -> str`. Lower the re-run timeout to 600s.

### 3. `pyproject.toml` — update marker description

```toml
markers = ["vm: integration test that boots a VM (OrbStack for Linux, tart for macOS; slow, opt-in)"]
```

`addopts` unchanged (`-m 'not vm'`). Single marker, single gate.

### 4. `justfile` — recipes

Existing `test-vm env="debian"` already supports `-k {{env}}`, so `just test-vm macos` works unchanged. Add a clarifying comment:

```
# env: debian | fedora | macos
test-vm env="debian":
    uv run pytest tests/test_vm_integration.py -v -m vm -k {{env}}
```

`test-vm-all` works as-is — the fixture's `VmBackendUnavailable → pytest.skip` makes it correct on Linux (skips macos), Intel Mac (skips macos), and Apple Silicon (runs all three). `just ci` is **not** modified.

### 5. `CLAUDE.md` — one-line update

Add to the "Run" section:

```
just test-vm <env>      # opt-in: VM integration tests (debian/fedora via OrbStack, macos via tart)
```

## Critical files

Modified:
- `src/dotgen/vm.py` — backend protocol + `_OrbBackend` + `_TartBackend`; `VmHandle` carries backend; `vm_session` dispatches by env; `_ensure_tart_image_cached` guard.
- `tests/test_vm_integration.py` — `MACOS_IMAGE` digest-pinned constant; `IMAGES` adds `macos`; fixture handles deploy-prefix + timeout per env; catches `VmBackendUnavailable` → skip; `test_fedora_full_addons` → `test_full_addons`; new `test_ghostty_app_installed`; selective `login=True` on existing tests.
- `pyproject.toml` — marker description updated to mention both backends.
- `justfile` — comment on `test-vm` recipe (no behavior change).
- `CLAUDE.md` — one-line addendum to the Run section.

New:
- (none — single-marker, single-test-file design)

Existing code reused (no edits):
- `src/dotgen/render.py::build_env`
- `src/dotgen/environment.py::ENVIRONMENTS["macos"]`
- `dist/macos/setup.sh` `deploy` mode + `dist/macos/os_shim.sh`
- `VmCommandError`, `_stream_block`, `_as_text` in `src/dotgen/vm.py` (unchanged signatures).

## Verification

```bash
# Pre-flight (one-time):
brew install cirruslabs/cli/tart hudochenkov/sshpass/sshpass
pin=$(rg -No 'MACOS_IMAGE\s*=\s*"([^"]+)"' -r '$1' tests/test_vm_integration.py)
tart pull "$pin"                             # ~30 GB; no-op on subsequent runs (digest-immutable)

just build-all                               # baseline
just test-vm debian                          # ~3–5 min, OrbBackend
just test-vm fedora                          # ~5–7 min, OrbBackend
just test-vm macos                           # ~15–25 min, TartBackend
just test-vm-all                             # all three, in series
orb list                                     # empty after clean run
tart list                                    # empty after clean run

# Forensics:
KEEP_VM=1 just test-vm macos                 # leaves dotgen-test-macos-<uid>
ssh admin@$(tart ip dotgen-test-macos-<uid>) # password: admin
tart stop dotgen-test-macos-<uid> && tart delete dotgen-test-macos-<uid>

# Cross-host:
# Linux dev box:   just test-vm-all          # macos leg skips with VmBackendUnavailable; debian+fedora run.
# Intel Mac:       just test-vm-all          # macos leg skips ("requires Apple Silicon"); debian+fedora run.

# CI invariant:
just ci                                      # green; runtime unchanged (vm marker excluded by addopts).
```

Spot-check the failure paths (mirrors Plan 05's spirit):

- Drop `kubectl` from `_SHARED` → `test_shared_tooling_installed` fails on all three envs; revert.
- Drop `Ghostty` from the macos env → `test_ghostty_app_installed` fails on macos (other envs skip cleanly); revert.
- Drop `Gcloud` → `test_full_addons` fails on fedora and macos (debian skips); revert.
- Add an unguarded `echo X >> ~/.bashrc` to a macos-touched component → idempotency assertion fails (sha mismatch); revert.
- Mistype the cask (`zedd`) → `brew install --cask` fails inside `setup.sh deploy`, fixture surfaces as `VmCommandError` with stderr; revert.
- Uninstall `sshpass` and rerun `just test-vm macos` → leg skips with `VmBackendUnavailable: tart backend unavailable: sshpass not on PATH`. `debian`/`fedora` legs unaffected.
- Replace `MACOS_IMAGE` with a tag-form ref (`...:latest`) → fixture skips with `VmBackendUnavailable: tart image must be digest-pinned`. Revert.
- Move the cached image aside (`mv ~/.tart/cache/OCIs/ghcr.io ~/.tart/cache/OCIs/ghcr.io.bak`) and rerun → fixture skips with a clear "run `tart pull <ref>` first (~30 GB)" message; never starts a download. Restore the cache to recover.
- `KEEP_VM=1` actually leaves the VM around (`tart list` shows it, `tart ip` resolves) and explicit `tart stop && tart delete` cleans up. The background `tart run` Popen is still alive — `pkill -f "tart run --no-graphics dotgen-test-macos-<uid>"` if you don't `tart stop` first.
