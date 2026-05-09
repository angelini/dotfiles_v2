import re
from pathlib import Path

import pytest

from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_env
from dotgen.secrets import all_keys

_TEMPLATE_CALL_RE = re.compile(
    r"install_config_template\s+\S+\s+\S+\s+'([^']+)'",
)
_TEMPLATE_KEY_RE = re.compile(r'^([A-Z][A-Z0-9_]*)="', re.MULTILINE)


@pytest.fixture(scope="module")
def built_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("dist_secrets")
    for name, env in ENVIRONMENTS.items():
        build_env(env, root / name)
    return root


def _keys_referenced_in_setup(setup_text: str) -> set[str]:
    keys: set[str] = set()
    for match in _TEMPLATE_CALL_RE.finditer(setup_text):
        keys.update(match.group(1).split())
    return keys


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
def test_template_lists_every_referenced_key(built_root: Path, env_name: str) -> None:
    setup = (built_root / env_name / "setup.sh").read_text()
    referenced = _keys_referenced_in_setup(setup)
    if not referenced:
        return
    template = built_root / env_name / "config" / "dotgen" / "secrets.env.template"
    assert template.exists(), f"{env_name}: template missing despite referenced keys {referenced}"
    declared = set(_TEMPLATE_KEY_RE.findall(template.read_text()))
    assert declared == referenced, f"{env_name}: template/setup mismatch (only_in_template={declared - referenced}, only_in_setup={referenced - declared})"


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
def test_no_unregistered_keys(built_root: Path, env_name: str) -> None:
    setup = (built_root / env_name / "setup.sh").read_text()
    referenced = _keys_referenced_in_setup(setup)
    unknown = referenced - set(all_keys())
    assert not unknown, f"{env_name}: keys referenced in setup.sh but missing from SecretKey: {unknown}"


def test_at_least_one_env_has_secrets(built_root: Path) -> None:
    found = False
    for env_name in ENVIRONMENTS:
        if (built_root / env_name / "config" / "dotgen" / "secrets.env.template").exists():
            found = True
            break
    assert found, "no env emitted a secrets.env.template; expected git_setup to declare keys"
