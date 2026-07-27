from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_env
from dotgen.vm import VmBackendUnavailable, VmHandle, vm_session

pytestmark = pytest.mark.vm

# Digest-pinned
# Refresh: `tart pull ghcr.io/cirruslabs/macos-sequoia-base:latest`,
#          capture digest via `tart fqn`, update below.
MACOS_IMAGE = "ghcr.io/cirruslabs/macos-sequoia-base@sha256:cae088989568978bcc9e5caf8eeabd02e68bf3317e765aafd5491a9db8924663"

IMAGES = {
    "debian": "debian:trixie",
    "debian-docker": "dist/debian-docker",
    "macos": MACOS_IMAGE,
}

_DEPLOY_TIMEOUT = {"debian": 900, "debian-docker": 900, "macos": 1800}
_REDEPLOY_TIMEOUT = {"debian": 600, "debian-docker": 600, "macos": 600}


def _deploy_cmd(env_name: str) -> str:
    prefix = 'eval "$(/opt/homebrew/bin/brew shellenv)" && ' if env_name == "macos" else ""
    return f"{prefix}bash /tmp/dotgen/{env_name}/setup.sh deploy"


def _stub_secrets_env(template_path: Path) -> str:
    return template_path.read_text().replace('=""', '="test"')


@pytest.fixture(scope="module", params=list(IMAGES), ids=["debian", "docker", "macos"])
def vm(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, VmHandle]]:
    env_name: str = request.param
    work = tmp_path_factory.mktemp(f"vm-{env_name}")
    build_env(ENVIRONMENTS[env_name], work / env_name)
    artifact_root = work / env_name / "artifacts" / "stinkpot"
    expected_targets = {"darwin-arm64"} if env_name == "macos" else {"linux-amd64", "linux-arm64"}
    assert {path.parent.name for path in artifact_root.glob("*/stinkpot")} == expected_targets
    assert (artifact_root / "SHA256SUMS").is_file()

    image_spec = str(work / env_name) if env_name == "debian-docker" else IMAGES[env_name]

    tar_base = str(work / env_name)
    tar = shutil.make_archive(tar_base, "gztar", root_dir=str(work), base_dir=env_name)

    secrets_local = work / "secrets.env"
    secrets_local.write_text(_stub_secrets_env(work / env_name / "config" / "dotgen" / "secrets.env.template"))

    try:
        with vm_session(env_name, image_spec) as handle:
            if env_name == "debian":
                handle.assert_cmd("sudo -n true")
                handle.prepare_rootless_container_subids()
            handle.push(Path(tar), "/tmp/dotgen.tar.gz")
            handle.push(secrets_local, "/tmp/secrets.env")
            handle.run("mkdir -p /tmp/dotgen && tar xzf /tmp/dotgen.tar.gz -C /tmp/dotgen")
            handle.run('mkdir -p "$HOME/.config/dotgen" && mv /tmp/secrets.env "$HOME/.config/dotgen/secrets.env"')
            handle.run("printf 'dotgen-stinkpot-legacy\\n' > \"$HOME/.bash_history\"")
            handle.run(_deploy_cmd(env_name), timeout=_DEPLOY_TIMEOUT[env_name])
            yield env_name, handle
    except VmBackendUnavailable as e:
        pytest.skip(str(e))


def _assert_debian_rootless_docker(handle: VmHandle) -> None:
    handle.assert_cmd(
        r"""
set -euo pipefail
user="$(id -un)" uid="$(id -u)"
awk -F: -v user="$user" -v uid="$uid" '$1 == user || $1 == uid { if ($3 ~ /^[0-9]+$/ && $3 >= 65536 && $2 + $3 - 1 <= 4294967295) found=1 } END { exit !found }' /etc/subuid
awk -F: -v user="$user" -v gid="$(id -g)" '$1 == user || $1 == gid { if ($3 ~ /^[0-9]+$/ && $3 >= 65536 && $2 + $3 - 1 <= 4294967295) found=1 } END { exit !found }' /etc/subgid
[ "$(systemctl is-enabled docker.service)" = masked ]
[ "$(systemctl is-enabled docker.socket)" = masked ]
! systemctl is-active --quiet docker.service
! systemctl is-active --quiet docker.socket
[ ! -e /var/run/docker.sock ]
[ "$(docker context show)" = rootless ]
[ "$(docker context inspect rootless --format '{{.Endpoints.docker.Host}}')" = "unix:///run/user/$uid/docker.sock" ]
[ -S "/run/user/$uid/docker.sock" ] && [ "$(stat -c %u "/run/user/$uid/docker.sock")" = "$uid" ]
systemctl --user is-enabled docker.service
systemctl --user is-active docker.service
docker info --format '{{json .SecurityOptions}}' | grep -q rootless
[ "$(docker info --format '{{.CgroupVersion}}')" = 2 ]
! id -nG | tr ' ' '\n' | grep -qx docker
docker run --rm hello-world
repo="$HOME/repos/docker-sandbox-smoke"; mkdir -p "$repo"
cat > "$repo/pi" <<'SH'
#!/usr/bin/env bash
[ ! -e "$XDG_RUNTIME_DIR/docker.sock" ]
SH
chmod +x "$repo/pi"
(cd "$repo" && PATH="$PWD:$PATH" pi-sandbox)
rm -rf "$repo"
""",
        login=True,
    )


def test_rootless_engine(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    if env_name != "debian":
        pytest.skip("rootless Docker is only full Debian")
    _assert_debian_rootless_docker(handle)


def test_core_utils_installed(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd(
        "command -v jq && command -v rg && command -v fd && command -v tree && command -v htop",
        login=True,
    )


def test_shared_tooling_installed(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    cmds = ["command -v kubectl", "command -v helm", "command -v starship", "command -v zoxide", "command -v gh"]
    if env_name != "debian-docker":
        cmds.extend(["command -v uv", "command -v claude"])
    handle.assert_cmd(" && ".join(cmds), login=True)


def test_stinkpot_is_bundled_installed_and_migrated(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    expected_os = "darwin" if env_name == "macos" else "linux"
    handle.assert_cmd(
        rf"""
set -euo pipefail
case "$(uname -m)" in
  x86_64) target={expected_os}-amd64 ;;
  arm64|aarch64) target={expected_os}-arm64 ;;
  *) exit 1 ;;
esac
bundle="/tmp/dotgen/{env_name}/artifacts/stinkpot/$target/stinkpot"
[ -x "$bundle" ]
[ -x "$HOME/bin/stinkpot" ]
cmp -s "$bundle" "$HOME/bin/stinkpot"
command -v stinkpot
[ "$HISTFILE" = /dev/null ]
grep -Fx 'dotgen-stinkpot-legacy' "$HOME/.bash_history"
stinkpot list | grep -F 'dotgen-stinkpot-legacy'
[ -f "${{XDG_STATE_HOME:-$HOME/.local/state}}/dotgen/stinkpot/bash-history-import-v1" ]
! grep -Eq 'tangled.org|go build|GOTOOLCHAIN' "/tmp/dotgen/{env_name}/setup.sh"
""",
        login=True,
    )
    mode_command = "stat -f '%Lp'" if env_name == "macos" else "stat -c '%a'"
    result = handle.run(
        f'{mode_command} "${{XDG_DATA_HOME:-$HOME/.local/share}}/stinkpot"; {mode_command} "${{XDG_DATA_HOME:-$HOME/.local/share}}/stinkpot/history.db"',
        login=True,
    )
    assert result.stdout.splitlines() == ["700", "600"]


def test_stinkpot_records_across_processes_and_handles_concurrency(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd(
        r"""
set -euo pipefail
command="dotgen-stinkpot-cross-process-$$"
export command
bash --noprofile --norc -ic 'source "$HOME/.bashrc"; history -s "$command"; (exit 37); __stinkpot_record'
stinkpot list | awk -F '\t' -v command="$command" '$2 == 37 && $3 == command { found=1 } END { exit !found }'
errors="$(mktemp)"
for i in 1 2 3 4 5 6 7 8; do
  stinkpot add --exit "$i" -- "dotgen-stinkpot-concurrent-$i" 2>>"$errors" &
done
wait
! grep -qi 'locked' "$errors"
rm -f "$errors"
""",
        login=True,
    )


def test_helix_installed(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd("command -v hx && [ -f $HOME/.config/helix/config.toml ]", login=True)


def test_git_config_uses_helix(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd("grep -q 'editor = hx' $HOME/.gitconfig")


def test_login_shell_sets_editor_to_hx(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    result = handle.run("echo $EDITOR", login=True)
    assert result.stdout.strip() == "hx", f"EDITOR={result.stdout!r}"


def test_login_shell_loads_kubectl_alias(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd("alias kc", login=True)


def test_pi_sandbox_blocks_home_secret_access(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    cmd = r"""
set -euo pipefail
mkdir -p "$HOME/repos/sandbox-smoke" "$HOME/.ssh"
printf 'secret\n' > "$HOME/.ssh/sandbox-secret"
cat > "$HOME/repos/sandbox-smoke/pi" <<'SH'
#!/usr/bin/env bash
cat "$HOME/.ssh/sandbox-secret"
SH
chmod +x "$HOME/repos/sandbox-smoke/pi"
cd "$HOME/repos/sandbox-smoke"
[ "$(./pi)" = secret ]
if PATH="$PWD:$PATH" pi-sandbox >/tmp/pi-sandbox-secret.out 2>/tmp/pi-sandbox-secret.err; then
  echo "pi-sandbox unexpectedly read ~/.ssh/sandbox-secret"
  cat /tmp/pi-sandbox-secret.out
  exit 1
fi
if grep -q secret /tmp/pi-sandbox-secret.out; then
  echo "pi-sandbox exposed ~/.ssh/sandbox-secret"
  cat /tmp/pi-sandbox-secret.out
  exit 1
fi
"""
    handle.assert_cmd(cmd, login=True)


def test_node_and_npm_installed(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd("command -v node && command -v npm", login=True)


def test_pi_launches_through_sandbox(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    if env_name == "debian-docker":
        pytest.skip("Docker does not allow the unprivileged user namespace required by bubblewrap")
    handle.assert_cmd('cd "$HOME/repos" && pi --version', login=True)


def test_pi_sandbox_exposes_developer_state_without_credentials(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    if env_name == "debian-docker":
        pytest.skip("Docker does not allow the unprivileged user namespace required by bubblewrap")
    cmd = r"""
set -euo pipefail
mkdir -p "$HOME/repos/sandbox-smoke" "$HOME/.config/git" "$HOME/.config/helm/registry"
printf '[user]\n  name = Sandbox User\n' > "$HOME/.config/git/config"
printf 'git-secret\n' > "$HOME/.config/git/credentials"
printf 'helm-registry-secret\n' > "$HOME/.config/helm/registry/config.json"
printf 'helm-repository-secret\n' > "$HOME/.config/helm/repositories.yaml"
cat > "$HOME/repos/sandbox-smoke/pi" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
transformers_cache="$(npm root -g)/@samfp/pi-memory/node_modules/@xenova/transformers/.cache"
for dir in \
  "$HOME/.pi" \
  "$HOME/.cache" \
  "$HOME/.config" \
  "$HOME/.cargo" \
  "$HOME/.local/share" \
  "$HOME/.local/state" \
  "$HOME/.npm" \
  "$HOME/go"
do
  printf 'state\n' > "$dir/sandbox-smoke"
done
printf 'cache\n' > "$transformers_cache/sandbox-smoke"
[ -r "$HOME/.gitconfig" ]
grep -q 'Sandbox User' "$HOME/.config/git/config"
[ ! -e "$HOME/.config/dotgen/secrets.env" ]
[ ! -s "$HOME/.config/gh/hosts.yml" ]
[ ! -s "$HOME/.config/git/credentials" ]
[ ! -s "$HOME/.config/helm/registry/config.json" ]
[ ! -s "$HOME/.config/helm/repositories.yaml" ]
for path in \
  "$HOME/.config/git/config" \
  "$HOME/.cargo/credentials.toml" \
  "$HOME/.cargo/bin/sandbox-smoke"
do
  if printf 'unexpected write\n' > "$path" 2>/dev/null; then
    echo "read-only path unexpectedly writable: $path"
    exit 1
  fi
done
SH
chmod +x "$HOME/repos/sandbox-smoke/pi"
cd "$HOME/repos/sandbox-smoke"
PATH="$PWD:$PATH" pi-sandbox
for path in \
  "$HOME/.pi/sandbox-smoke" \
  "$HOME/.cache/sandbox-smoke" \
  "$HOME/.config/sandbox-smoke" \
  "$HOME/.cargo/sandbox-smoke" \
  "$HOME/.local/share/sandbox-smoke" \
  "$HOME/.local/state/sandbox-smoke" \
  "$HOME/.npm/sandbox-smoke" \
  "$HOME/go/sandbox-smoke"
do
  [ "$(cat "$path")" = state ]
done
transformers_cache="$(npm root -g)/@samfp/pi-memory/node_modules/@xenova/transformers/.cache"
if [ -f "$HOME/.pi/memory/transformers-cache/sandbox-smoke" ]; then
  [ "$(cat "$HOME/.pi/memory/transformers-cache/sandbox-smoke")" = cache ]
else
  [ "$(cat "$transformers_cache/sandbox-smoke")" = cache ]
fi
grep -q 'Sandbox User' "$HOME/.config/git/config"
[ "$(cat "$HOME/.config/git/credentials")" = git-secret ]
[ "$(cat "$HOME/.config/helm/registry/config.json")" = helm-registry-secret ]
[ "$(cat "$HOME/.config/helm/repositories.yaml")" = helm-repository-secret ]
"""
    handle.assert_cmd(cmd, login=True)


def test_pi_sandbox_hides_stinkpot_database(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    if env_name == "debian-docker":
        pytest.skip("Docker does not allow the unprivileged user namespace required by bubblewrap")
    sum_cmd = "shasum -a 256" if env_name == "macos" else "sha256sum"
    before = handle.run(f'{sum_cmd} "${{XDG_DATA_HOME:-$HOME/.local/share}}/stinkpot/history.db"').stdout
    handle.assert_cmd(
        r"""
set -euo pipefail
repo="$HOME/repos/stinkpot-sandbox-smoke"
mkdir -p "$repo"
cat > "$repo/pi" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
db="${XDG_DATA_HOME:-$HOME/.local/share}/stinkpot/history.db"
if cat "$db" >/tmp/stinkpot-visible 2>/dev/null; then
  exit 1
fi
printf 'shadow write\n' > "$db" 2>/dev/null || true
SH
chmod +x "$repo/pi"
(cd "$repo" && PATH="$PWD:$PATH" pi-sandbox)
""",
        login=True,
    )
    after = handle.run(f'{sum_cmd} "${{XDG_DATA_HOME:-$HOME/.local/share}}/stinkpot/history.db"').stdout
    assert before == after


def test_full_addons(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    if env_name == "debian-docker":
        pytest.skip("Full addons excluded from debian-docker")
    handle.assert_cmd(
        "command -v cargo && command -v fnm && command -v go && command -v aws && command -v gcloud",
        login=True,
    )
    if env_name == "macos":
        handle.assert_cmd("command -v zed", login=True)


def test_ghostty_app_installed(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    if env_name != "macos":
        pytest.skip("Ghostty is only included on macos")
    handle.assert_cmd('[ -d "/Applications/Ghostty.app" ]')


def test_setup_is_idempotent(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    sum_cmd = "sha256sum" if env_name != "macos" else "shasum -a 256"
    state = "${XDG_STATE_HOME:-$HOME/.local/state}/dotgen/stinkpot/bash-history-import-v1"
    database = "${XDG_DATA_HOME:-$HOME/.local/share}/stinkpot/history.db"
    tracked = f'$HOME/.bashrc $HOME/.aliases $HOME/.gitconfig $HOME/bin/stinkpot "{state}" "{database}"'
    mtime_cmd = "stat -f '%m'" if env_name == "macos" else "stat -c '%Y'"
    before = handle.run(f"{sum_cmd} {tracked}; {mtime_cmd} $HOME/bin/stinkpot").stdout
    handle.run(_deploy_cmd(env_name), timeout=_REDEPLOY_TIMEOUT[env_name])
    after = handle.run(f"{sum_cmd} {tracked}; {mtime_cmd} $HOME/bin/stinkpot").stdout
    assert before == after, f"second setup.sh run mutated dotfiles\nbefore:\n{before}\nafter:\n{after}"
    if env_name == "debian":
        _assert_debian_rootless_docker(handle)
