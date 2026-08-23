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
_FAKE_NPM_TOKEN = "dotgen-vm-test-not-a-real-token"


def _deploy_cmd(env_name: str) -> str:
    prefix = 'eval "$(/opt/homebrew/bin/brew shellenv)" && ' if env_name == "macos" else ""
    return f"{prefix}bash /tmp/dotgen/{env_name}/setup.sh deploy"


def _stub_secrets_env(template_path: Path) -> str:
    template = template_path.read_text()
    assert 'NPM_TOKEN=""' in template
    return template.replace('NPM_TOKEN=""', f'NPM_TOKEN="{_FAKE_NPM_TOKEN}"').replace('=""', '="test"')


@pytest.fixture(scope="module", params=list(IMAGES), ids=["debian", "docker", "macos"])
def vm(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, VmHandle]]:
    env_name: str = request.param
    work = tmp_path_factory.mktemp(f"vm-{env_name}")
    build_env(ENVIRONMENTS[env_name], work / env_name)
    assert not (work / env_name / "artifacts").exists()

    image_spec = str(work / env_name) if env_name == "debian-docker" else IMAGES[env_name]

    tar_base = str(work / env_name)
    tar = shutil.make_archive(tar_base, "gztar", root_dir=str(work), base_dir=env_name)

    secrets_template = work / env_name / "config" / "dotgen" / "secrets.env.template"
    secrets_local = work / "secrets.env"
    secrets_local.write_text(_stub_secrets_env(secrets_template))
    if env_name == "debian-docker":
        secrets_template.write_text(secrets_local.read_text())

    try:
        with vm_session(env_name, image_spec) as handle:
            if env_name != "debian-docker":
                handle.prepare_passwordless_sudo()
            if env_name == "debian":
                handle.prepare_rootless_container_subids()
            handle.push(Path(tar), "/tmp/dotgen.tar.gz")
            handle.push(secrets_local, "/tmp/secrets.env")
            handle.run("mkdir -p /tmp/dotgen && tar xzf /tmp/dotgen.tar.gz -C /tmp/dotgen")
            handle.run('mkdir -p "$HOME/.config/dotgen" && mv /tmp/secrets.env "$HOME/.config/dotgen/secrets.env"')
            handle.run(
                r'''mkdir -p "$HOME/bin" "$HOME/.local/share/stinkpot" "$HOME/.local/state/dotgen/stinkpot"
printf 'dotgen-bash-history-legacy\n' > "$HOME/.bash_history"
printf 'legacy-binary\n' > "$HOME/bin/stinkpot"
printf 'legacy-database\n' > "$HOME/.local/share/stinkpot/history.db"
printf 'legacy-wal\n' > "$HOME/.local/share/stinkpot/history.db-wal"
printf 'legacy-shm\n' > "$HOME/.local/share/stinkpot/history.db-shm"
printf 'legacy-marker\n' > "$HOME/.local/state/dotgen/stinkpot/bash-history-import-v1"
chmod 0600 "$HOME/.bash_history" "$HOME/.local/share/stinkpot/"* "$HOME/.local/state/dotgen/stinkpot/bash-history-import-v1"
chmod 0755 "$HOME/bin/stinkpot"'''
            )
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
        "command -v jq && command -v just && command -v rg && command -v fd && command -v eza && command -v bat && command -v delta && command -v tree && command -v htop && command -v btop",
        login=True,
    )


def test_shared_tooling_installed(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    cmds = ["command -v kubectl", "command -v helm", "command -v starship", "command -v zoxide", "command -v gh"]
    if env_name != "debian-docker":
        cmds.extend(["command -v uv", "command -v claude"])
    handle.assert_cmd(" && ".join(cmds), login=True)


def test_tmux_and_mosh_remote_session_setup(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    if env_name == "debian-docker":
        handle.assert_cmd(
            r"""
set -euo pipefail
! grep -q 'component_begin "tmux"' /tmp/dotgen/debian-docker/setup.sh
! grep -q 'component_begin "mosh"' /tmp/dotgen/debian-docker/setup.sh
! grep -q 'component_begin "tmuxinator"' /tmp/dotgen/debian-docker/setup.sh
! grep -q '^# --- tmux ---$' /tmp/dotgen/debian-docker/alias.sh
! grep -q '^# --- mosh ---$' /tmp/dotgen/debian-docker/alias.sh
[ ! -e /tmp/dotgen/debian-docker/config/tmux ]
[ ! -e /tmp/dotgen/debian-docker/config/tmuxinator ]
! type ta >/dev/null 2>&1
! type mosh-agent >/dev/null 2>&1
""",
            login=True,
        )
        return

    helper_check = "type mosh-agent" if env_name == "macos" else "! type mosh-agent >/dev/null 2>&1"
    handle.assert_cmd(
        rf"""
set -euo pipefail
command -v tmux
command -v mosh
infocmp tmux-256color >/dev/null
cmp -s "$HOME/.tmux.conf" /tmp/dotgen/{env_name}/config/tmux/tmux.conf
type ta
{helper_check}
socket="dotgen-test-$$"
term_file="$(mktemp)"
cleanup() {{
  tmux -L "$socket" kill-server 2>/dev/null || true
  rm -f "$term_file"
}}
trap cleanup EXIT HUP INT TERM
tmux -L "$socket" -f "$HOME/.tmux.conf" new-session -d -s config-check "printf '%s\\n' \"\$TERM\" > '$term_file'; exec sleep 30"
for _ in 1 2 3 4 5; do
  [ -s "$term_file" ] && break
  sleep 1
done
[ "$(cat "$term_file")" = tmux-256color ]
[ "$(tmux -L "$socket" show-options -gv mouse)" = on ]
[ "$(tmux -L "$socket" show-options -gv history-limit)" = 100000 ]
[ "$(tmux -L "$socket" show-options -gv base-index)" = 1 ]
[ "$(tmux -L "$socket" show-options -gv renumber-windows)" = on ]
[ "$(tmux -L "$socket" show-options -sv escape-time)" = 10 ]
""",
        login=True,
    )

    if env_name == "macos":
        handle.assert_cmd(
            r"""
! grep -q 'component_begin "tmuxinator"' /tmp/dotgen/macos/setup.sh
[ ! -e /tmp/dotgen/macos/config/tmuxinator ]
"""
        )
        return

    handle.assert_cmd(
        r"""
set -euo pipefail
command -v tmuxinator
[ -x /usr/local/bin/dotgen-agent-session ]
cmp -s /usr/local/bin/dotgen-agent-session /tmp/dotgen/debian/config/tmuxinator/dotgen-agent-session
cmp -s "$HOME/.config/dotgen/tmuxinator/default.yml" /tmp/dotgen/debian/config/tmuxinator/default.yml
project="dotgen_tmuxinator_vm_$$"
root="$HOME/repos/$project"
config="$HOME/.config/tmuxinator/$project.yml"
fake_bin="$(mktemp -d)"
expected="$(mktemp)"
cleanup() {
  tmux kill-session -t "=$project" 2>/dev/null || true
  rm -rf "$fake_bin" "$root"
  rm -f "$config" "$expected"
}
trap cleanup EXIT HUP INT TERM
mkdir -p "$root"
sed "s/<%= name %>/$project/g" /tmp/dotgen/debian/config/tmuxinator/default.yml > "$expected"
dotgen-agent-session init "$project" >/dev/null &
first_init_pid=$!
dotgen-agent-session init "$project" >/dev/null &
second_init_pid=$!
wait "$first_init_pid"
wait "$second_init_pid"
cmp -s "$config" "$expected"
first_inode="$(stat -c '%i' "$config")"
dotgen-agent-session init "$project" >/dev/null
[ "$(stat -c '%i' "$config")" = "$first_inode" ]
TMUXINATOR_CONFIG="$HOME/.config/tmuxinator" tmuxinator debug "$project" | grep -q 'even-horizontal'
cat > "$fake_bin/hx" <<'EOF'
#!/usr/bin/env bash
printf 'DOTGEN_HX_STARTED\n'
exec sleep 30
EOF
cat > "$fake_bin/claude" <<'EOF'
#!/usr/bin/env bash
printf 'DOTGEN_CLAUDE_STARTED\n'
exec sleep 30
EOF
chmod 0755 "$fake_bin/hx" "$fake_bin/claude"
PATH="$fake_bin:$PATH" TMUXINATOR_CONFIG="$HOME/.config/tmuxinator" tmuxinator start --no-attach "$project"
[ "$(tmux list-windows -t "=$project" -F '#W' | paste -sd, -)" = work,agents ]
[ "$(tmux list-panes -t "$project:work" | wc -l | tr -d ' ')" = 2 ]
set -- $(tmux list-panes -t "$project:work" -F '#{pane_width}')
left_width="$1"
right_width="$2"
[ "$((left_width - right_width))" -ge -1 ] && [ "$((left_width - right_width))" -le 1 ]
[ "$(tmux display-message -p -t "$project:work.0" '#{pane_active}')" = 1 ]
[ "$(tmux display-message -p -t "$project:work.0" '#{pane_current_path}')" = "$root" ]
[ "$(tmux display-message -p -t "$project:work.1" '#{pane_current_path}')" = "$root" ]
for _ in 1 2 3 4 5; do
  tmux capture-pane -p -t "$project:work.1" | grep -q DOTGEN_HX_STARTED &&
    tmux capture-pane -p -t "$project:agents.0" | grep -q DOTGEN_CLAUDE_STARTED && break
  sleep 1
done
tmux capture-pane -p -t "$project:work.1" | grep -q DOTGEN_HX_STARTED
tmux capture-pane -p -t "$project:agents.0" | grep -q DOTGEN_CLAUDE_STARTED
PATH="$fake_bin:$PATH" TMUXINATOR_CONFIG="$HOME/.config/tmuxinator" tmuxinator start --no-attach "$project"
[ "$(tmux list-windows -t "=$project" | wc -l | tr -d ' ')" = 2 ]
[ "$(tmux list-panes -s -t "=$project" | wc -l | tr -d ' ')" = 3 ]
if dotgen-agent-session reset "$project"; then
  exit 1
fi
tmux kill-session -t "=$project"
printf 'sentinel\n' > "$config"
dotgen-agent-session reset "$project"
cmp -s "$config" "$expected"
""",
        login=True,
    )


def test_fzf_bash_history_is_deployed_with_standard_bindings(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    mode_command = "stat -f '%Lp'" if env_name == "macos" else "stat -c '%a'"
    handle.assert_cmd(
        rf"""
set -euo pipefail
command -v fzf
fzf --version | awk '$1 + 0 >= 0.60 {{ found=1 }} END {{ exit !found }}'
[ "$({mode_command} "$HOME/.bash_history")" = 600 ]
grep -Fx 'dotgen-bash-history-legacy' "$HOME/.bash_history"
! grep -Eqi 'tangled.org|stinkpot_install|GOTOOLCHAIN|artifacts/stinkpot' "/tmp/dotgen/{env_name}/setup.sh"
bash --noprofile --norc -ic '
  source "$HOME/.bashrc"
  [ "$HISTFILE" = "$HOME/.bash_history" ]
  [ "$HISTSIZE" = 100000 ]
  [ "$HISTFILESIZE" = 100000 ]
  [ "$HISTCONTROL" = ignoreboth ]
  shopt -q histappend
  [ "$(printf "%s\n" $FZF_CTRL_R_OPTS | grep -o -- "--no-sort" | wc -l | tr -d " ")" = 1 ]
  bind -m emacs-standard -X | grep -F "__fzf_history__"
  bind -m vi-command -X | grep -F "__fzf_history__"
  bind -m vi-insert -X | grep -F "__fzf_history__"
  bind -m emacs-standard -X | grep -F "fzf-file-widget"
  bind -m emacs-standard -s | grep -F "__fzf_cd__"
  declare -f __fzf_history__ | grep -F -- "--bind=ctrl-r:toggle-sort"
'
""",
        login=True,
    )


def test_bash_history_shares_across_processes_and_preserves_concurrent_commands(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd(
        r"""
set -euo pipefail
history_file="$HOME/.bash_history"
command_a="dotgen-history-a-$$"
command_b="dotgen-history-b-$$"
export command_a command_b
bash --noprofile --norc -ic 'source "$HOME/.bashrc"; history -s "$command_a"; __dotgen_history_sync'
bash --noprofile --norc -ic 'source "$HOME/.bashrc"; history -n; history | grep -F "$command_a"'
(
  bash --noprofile --norc -ic 'source "$HOME/.bashrc"; history -s "$command_a-concurrent"; history -a'
) &
(
  bash --noprofile --norc -ic 'source "$HOME/.bashrc"; history -s "$command_b-concurrent"; history -a'
) &
wait
grep -F "$command_a-concurrent" "$history_file"
grep -F "$command_b-concurrent" "$history_file"
""",
        login=True,
    )


def test_helix_installed(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd(
        "command -v hx && grep -Fq 'theme = \"base16_default_light\"' $HOME/.config/helix/config.toml",
        login=True,
    )


def test_git_config_uses_helix_and_delta(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd(
        '[ "$(git config --global --get core.editor)" = hx ] && '
        '[ "$(git config --global --get core.pager)" = delta ] && '
        '[ "$(git config --global --get interactive.diffFilter)" = "delta --color-only" ]'
    )


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


def test_npm_config_uses_synthetic_token(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd(f"grep -Fqx '//npm.pkg.github.com/:_authToken={_FAKE_NPM_TOKEN}' \"$HOME/.npmrc\"")


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
mkdir -p "$HOME/repos/sandbox-smoke" "$HOME/.config/git" "$HOME/.config/helm/registry" "$HOME/.ssh"
printf '[user]\n  name = Sandbox User\n' > "$HOME/.config/git/config"
printf 'git-secret\n' > "$HOME/.config/git/credentials"
printf 'helm-registry-secret\n' > "$HOME/.config/helm/registry/config.json"
printf 'helm-repository-secret\n' > "$HOME/.config/helm/repositories.yaml"
cat > "$HOME/repos/sandbox-smoke/pi" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
process_substitution_output=
while IFS= read -r line; do
  process_substitution_output+="$line"
done < <(printf 'process-substitution\n')
[ "$process_substitution_output" = process-substitution ]
transformers_cache="$(npm root -g)/@samfp/pi-memory/node_modules/@xenova/transformers/.cache"
[ "$JITI_FS_CACHE" = 1 ]
if [ "$(uname -s)" = Darwin ]; then
  jiti_cache="$TMPDIR/jiti"
else
  jiti_cache=/tmp/jiti
  [ ! -e "$HOME/.pi-sandbox-cache" ]
fi
printf 'const value: number = 42;\nexport default value;\n' > "$PWD/jiti-cache-probe.ts"
jiti_entry="$(npm root -g)/@earendil-works/pi-coding-agent/node_modules/jiti/lib/jiti-static.mjs"
JITI_ENTRY="$jiti_entry" PROBE="$PWD/jiti-cache-probe.ts" node --input-type=module <<'JS'
const { createJiti } = await import(process.env.JITI_ENTRY);
const jiti = createJiti(import.meta.url, { moduleCache: false, tryNative: false });
const value = await jiti.import(process.env.PROBE, { default: true });
if (value !== 42) throw new Error(`unexpected Jiti probe result: ${value}`);
JS
find "$jiti_cache" -maxdepth 1 -type f -name '*jiti-cache-probe*' -print -quit | grep -q .
for dir in \
  "$HOME/.pi" \
  "$HOME/.pi-lens" \
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
if [ "$(uname -s)" = Darwin ]; then
  [ "$TMPDIR" = "$(cd "$TMPDIR" && pwd -P)" ]
  printf 'temp\n' > "$TMPDIR/dotgen-sandbox-smoke"
fi
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
if [ "$(uname -s)" != Darwin ]; then
  mkdir -p "$HOME/.pi-sandbox-cache"
  ln -s "$HOME/.ssh" "$HOME/.pi-sandbox-cache/jiti"
  if PATH="$PWD:$PATH" pi-sandbox > /tmp/pi-sandbox-jiti-symlink.out 2>&1; then
    echo "pi-sandbox accepted a symlinked Jiti cache" >&2
    exit 1
  fi
  grep -q 'refusing symlinked Jiti cache directory' /tmp/pi-sandbox-jiti-symlink.out
  rm -f "$HOME/.pi-sandbox-cache/jiti" /tmp/pi-sandbox-jiti-symlink.out
fi
PATH="$PWD:$PATH" pi-sandbox
if [ "$(uname -s)" = Darwin ]; then
  jiti_cache="${TMPDIR:-/tmp}/jiti"
else
  jiti_cache="$HOME/.pi-sandbox-cache/jiti"
fi
jiti_cache_file="$(find "$jiti_cache" -maxdepth 1 -type f -name '*jiti-cache-probe*' -print -quit)"
[ -n "$jiti_cache_file" ]
if [ "$(uname -s)" = Darwin ]; then
  jiti_cache_mtime="$(stat -f %m "$jiti_cache_file")"
else
  jiti_cache_mtime="$(stat -c %Y "$jiti_cache_file")"
fi
sleep 1
PATH="$PWD:$PATH" pi-sandbox
if [ "$(uname -s)" = Darwin ]; then
  [ "$(stat -f %m "$jiti_cache_file")" = "$jiti_cache_mtime" ]
else
  [ "$(stat -c %Y "$jiti_cache_file")" = "$jiti_cache_mtime" ]
fi
for path in \
  "$HOME/.pi/sandbox-smoke" \
  "$HOME/.pi-lens/sandbox-smoke" \
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
if [ "$(uname -s)" = Darwin ]; then
  [ "$(cat "${TMPDIR:-/tmp}/dotgen-sandbox-smoke")" = temp ]
  rm -f "${TMPDIR:-/tmp}/dotgen-sandbox-smoke"
fi
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


def test_pi_sandbox_hides_bash_history_and_legacy_stinkpot_database(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    if env_name == "debian-docker":
        pytest.skip("Docker does not allow the unprivileged user namespace required by bubblewrap")
    sum_cmd = "shasum -a 256" if env_name == "macos" else "sha256sum"
    before = handle.run(f'{sum_cmd} "$HOME/.bash_history" "${{XDG_DATA_HOME:-$HOME/.local/share}}/stinkpot/history.db"').stdout
    handle.assert_cmd(
        r"""
set -euo pipefail
repo="$HOME/repos/stinkpot-sandbox-smoke"
mkdir -p "$repo"
cat > "$repo/pi" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
db="${XDG_DATA_HOME:-$HOME/.local/share}/stinkpot/history.db"
for hidden in "$HOME/.bash_history" "$db"; do
  if cat "$hidden" >/tmp/dotgen-hidden-visible 2>/dev/null; then
    exit 1
  fi
  printf 'shadow write\n' > "$hidden" 2>/dev/null || true
done
SH
chmod +x "$repo/pi"
(cd "$repo" && PATH="$PWD:$PATH" pi-sandbox)
""",
        login=True,
    )
    after = handle.run(f'{sum_cmd} "$HOME/.bash_history" "${{XDG_DATA_HOME:-$HOME/.local/share}}/stinkpot/history.db"').stdout
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
    legacy = (
        ' $HOME/bin/stinkpot "${XDG_DATA_HOME:-$HOME/.local/share}/stinkpot/history.db"'
        ' "${XDG_DATA_HOME:-$HOME/.local/share}/stinkpot/history.db-wal"'
        ' "${XDG_DATA_HOME:-$HOME/.local/share}/stinkpot/history.db-shm"'
        ' "${XDG_STATE_HOME:-$HOME/.local/state}/dotgen/stinkpot/bash-history-import-v1"'
    )
    tmux_config = " $HOME/.tmux.conf" if env_name != "debian-docker" else ""
    if env_name == "debian":
        tmux_config += " $HOME/.config/dotgen/tmuxinator/default.yml /usr/local/bin/dotgen-agent-session"
    tracked = f"$HOME/.bashrc $HOME/.aliases $HOME/.gitconfig $HOME/.bash_history{tmux_config}{legacy}"
    mtime_cmd = "stat -f '%m'" if env_name == "macos" else "stat -c '%Y'"
    before = handle.run(f"{sum_cmd} {tracked}; {mtime_cmd} $HOME/bin/stinkpot").stdout
    handle.run(_deploy_cmd(env_name), timeout=_REDEPLOY_TIMEOUT[env_name])
    after = handle.run(f"{sum_cmd} {tracked}; {mtime_cmd} $HOME/bin/stinkpot").stdout
    assert before == after, f"second setup.sh run mutated dotfiles\nbefore:\n{before}\nafter:\n{after}"
    if env_name == "debian":
        _assert_debian_rootless_docker(handle)
