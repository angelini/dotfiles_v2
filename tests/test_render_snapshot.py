import os
import re
from pathlib import Path

import pytest

from dotgen.environment import ENVIRONMENTS
from dotgen.render import build_env

GOLDEN_ROOT = Path(__file__).parent / "golden"
SNAPSHOT_FILES = ("setup.sh", "alias.sh", ".bashrc", "os_shim.sh")
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


@pytest.fixture(scope="module")
def built_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("snapshot")
    for name, env in ENVIRONMENTS.items():
        build_env(env, root / name)
    return root


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
@pytest.mark.parametrize("fname", SNAPSHOT_FILES)
def test_snapshot_matches_golden(built_root: Path, env_name: str, fname: str) -> None:
    actual = (built_root / env_name / fname).read_text()
    golden = GOLDEN_ROOT / env_name / fname

    if UPDATE or not golden.exists():
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual)
        if not UPDATE:
            pytest.skip(f"created missing golden {golden.relative_to(GOLDEN_ROOT.parent)}")
        return

    assert actual == golden.read_text(), (
        f"snapshot drift for {env_name}/{fname}; "
        f"re-run with UPDATE_GOLDEN=1 if intended"
    )


_HEADER_RE = re.compile(r"^# --- ([a-z_][a-z_0-9]*) ---$", re.MULTILINE)


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
@pytest.mark.parametrize("fname", ("setup.sh", "alias.sh", ".bashrc"))
def test_chunk_headers_match_registered_components(
    built_root: Path, env_name: str, fname: str
) -> None:
    text = (built_root / env_name / fname).read_text()
    found = _HEADER_RE.findall(text)
    valid = {c.name for c in ENVIRONMENTS[env_name].components}
    unknown = [name for name in found if name not in valid]
    assert not unknown, f"unknown component headers in {env_name}/{fname}: {unknown}"


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
def test_setup_header_pairs_with_component_begin(built_root: Path, env_name: str) -> None:
    text = (built_root / env_name / "setup.sh").read_text()
    for match in _HEADER_RE.finditer(text):
        name = match.group(1)
        tail = text[match.end():]
        next_line = tail.lstrip("\n").split("\n", 1)[0]
        assert next_line == f'component_begin "{name}"', (
            f"expected component_begin after `# --- {name} ---` in setup.sh, got {next_line!r}"
        )


@pytest.mark.parametrize("env_name", list(ENVIRONMENTS))
@pytest.mark.parametrize("fname", ("setup.sh", "alias.sh", ".bashrc"))
def test_chunks_separated_by_blank_line(
    built_root: Path, env_name: str, fname: str
) -> None:
    text = (built_root / env_name / fname).read_text()
    headers = list(_HEADER_RE.finditer(text))
    for header in headers[1:]:
        preceding = text[: header.start()]
        assert preceding.endswith("\n\n"), (
            f"{env_name}/{fname}: header `{header.group(0)}` "
            f"is not preceded by a blank line"
        )
