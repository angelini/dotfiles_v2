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
    "fedora": "fedora:43",
    "macos": MACOS_IMAGE,
}

_DEPLOY_TIMEOUT = {"debian": 900, "fedora": 900, "macos": 1800}
_REDEPLOY_TIMEOUT = {"debian": 600, "fedora": 600, "macos": 600}


def _deploy_cmd(env_name: str) -> str:
    prefix = 'eval "$(/opt/homebrew/bin/brew shellenv)" && ' if env_name == "macos" else ""
    return f"{prefix}bash /tmp/dotgen/{env_name}/setup.sh deploy"


def _stub_secrets_env(template_path: Path) -> str:
    return template_path.read_text().replace('=""', '="test"')


@pytest.fixture(scope="module", params=list(IMAGES))
def vm(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, VmHandle]]:
    env_name: str = request.param
    work = tmp_path_factory.mktemp(f"vm-{env_name}")
    build_env(ENVIRONMENTS[env_name], work / env_name)
    tar_base = str(work / env_name)
    tar = shutil.make_archive(tar_base, "gztar", root_dir=str(work), base_dir=env_name)

    secrets_local = work / "secrets.env"
    secrets_local.write_text(_stub_secrets_env(work / env_name / "config" / "dotgen" / "secrets.env.template"))

    try:
        with vm_session(env_name, IMAGES[env_name]) as handle:
            handle.push(Path(tar), "/tmp/dotgen.tar.gz")
            handle.push(secrets_local, "/tmp/secrets.env")
            handle.run("mkdir -p /tmp/dotgen && tar xzf /tmp/dotgen.tar.gz -C /tmp/dotgen")
            handle.run('mkdir -p "$HOME/.config/dotgen" && mv /tmp/secrets.env "$HOME/.config/dotgen/secrets.env"')
            handle.run(_deploy_cmd(env_name), timeout=_DEPLOY_TIMEOUT[env_name])
            yield env_name, handle
    except VmBackendUnavailable as e:
        pytest.skip(str(e))


def test_core_utils_installed(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd(
        "command -v jq && command -v rg && command -v fd && command -v tree && command -v htop",
        login=True,
    )


def test_shared_tooling_installed(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd(
        "command -v kubectl && command -v helm && command -v starship && command -v zoxide && command -v uv && command -v gh && command -v claude",
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


def test_full_addons(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    if env_name == "debian":
        pytest.skip("debian env does not include full addons")
    handle.assert_cmd(
        "command -v cargo && command -v fnm && command -v go && command -v aws && command -v gcloud && command -v zed",
        login=True,
    )


def test_ghostty_app_installed(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    if env_name != "macos":
        pytest.skip("Ghostty is only included on macos")
    handle.assert_cmd('[ -d "/Applications/Ghostty.app" ]')


def test_setup_is_idempotent(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    before = handle.run("sha256sum $HOME/.bashrc $HOME/.aliases $HOME/.gitconfig").stdout
    handle.run(_deploy_cmd(env_name), timeout=_REDEPLOY_TIMEOUT[env_name])
    after = handle.run("sha256sum $HOME/.bashrc $HOME/.aliases $HOME/.gitconfig").stdout
    assert before == after, f"second setup.sh run mutated dotfiles\nbefore:\n{before}\nafter:\n{after}"
