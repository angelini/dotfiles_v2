from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from dotgen.environment import ENVIRONMENTS
from dotgen.render import build_env
from dotgen.vm import VmHandle, vm_session

pytestmark = pytest.mark.vm

IMAGES = {"debian": "debian:trixie", "fedora": "fedora:43"}


@pytest.fixture(scope="module", params=list(IMAGES))
def vm(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[str, VmHandle]]:
    env_name: str = request.param
    work = tmp_path_factory.mktemp(f"vm-{env_name}")
    build_env(ENVIRONMENTS[env_name], work / env_name)
    tar_base = str(work / env_name)
    tar = shutil.make_archive(tar_base, "gztar", root_dir=str(work), base_dir=env_name)

    with vm_session(env_name, IMAGES[env_name]) as handle:
        handle.push(Path(tar), "/tmp/dotgen.tar.gz")
        handle.run("mkdir -p /tmp/dotgen && tar xzf /tmp/dotgen.tar.gz -C /tmp/dotgen")
        handle.run(f"bash /tmp/dotgen/{env_name}/setup.sh deploy", timeout=900)
        yield env_name, handle


def test_core_utils_installed(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd("command -v jq && command -v rg && command -v fd && command -v tree && command -v htop")


def test_shared_tooling_installed(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd(
        "command -v kubectl && command -v helm && command -v starship && "
        "command -v zoxide && command -v uv && command -v gh && command -v claude"
    )


def test_helix_installed(vm: tuple[str, VmHandle]) -> None:
    _, handle = vm
    handle.assert_cmd("command -v hx && [ -f $HOME/.config/helix/config.toml ]")


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


def test_fedora_full_addons(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    if env_name != "fedora":
        pytest.skip("full addons only on fedora")
    handle.assert_cmd(
        "command -v cargo && command -v fnm && command -v go && command -v aws && command -v zed"
    )


def test_setup_is_idempotent(vm: tuple[str, VmHandle]) -> None:
    env_name, handle = vm
    before = handle.run("sha256sum $HOME/.bashrc $HOME/.aliases $HOME/.gitconfig").stdout
    handle.run(f"bash /tmp/dotgen/{env_name}/setup.sh deploy", timeout=600)
    after = handle.run("sha256sum $HOME/.bashrc $HOME/.aliases $HOME/.gitconfig").stdout
    assert before == after, f"second setup.sh run mutated dotfiles\nbefore:\n{before}\nafter:\n{after}"
