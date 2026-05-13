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

    # Some keys are used directly by components (e.g. for environment variables)
    # but not via install_config_template. We don't track them in setup.sh references
    # for whitelisting purposes, but they are emitted in the secrets template.
    # The current test only checks keys whitelisted for templates.
    return keys


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
def test_template_lists_every_referenced_key(built_root: Path, env_name: str) -> None:
    setup = (built_root / env_name / "setup.sh").read_text()
    referenced = _keys_referenced_in_setup(setup)

    template_file = built_root / env_name / "config" / "dotgen" / "secrets.env.template"
    if not referenced:
        # If no templates, we might still have secrets emitted for other reasons
        return

    assert template_file.exists(), f"{env_name}: template missing despite referenced keys {referenced}"
    declared = set(_TEMPLATE_KEY_RE.findall(template_file.read_text()))

    # Only verify keys that are actually whitelisted in setup.sh for templates.
    # Keys used directly as env vars (like EXA_API_KEY) are fine to be in the template
    # without being in 'referenced' (which tracks template whitelists).
    missing_in_template = referenced - declared
    assert not missing_in_template, f"{env_name}: whitelisted keys missing from template: {missing_in_template}"


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
