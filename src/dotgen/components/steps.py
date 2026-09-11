import os
from dataclasses import dataclass
from pathlib import Path

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.vendor import VendorDir

_SETUP = r"""uv_bin="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"
if [ ! -x "$uv_bin" ]; then
  error "steps: uv not found"
  exit 1
fi
install_config_dir "$DIR/config/steps" "$HOME/.local/share/steps" "steps"
"$uv_bin" tool install --reinstall "$HOME/.local/share/steps"
"""


def _steps_root() -> Path:
    configured = os.environ.get("DOTGEN_STEPS_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4] / "steps"


@dataclass(frozen=True)
class Steps:
    name: str = "steps"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP,
            vendors=(
                VendorDir(
                    source=_steps_root(),
                    dest="steps",
                    include_globs=(
                        "pyproject.toml",
                        "README.md",
                        "package.json",
                        "src/**",
                        "skills/**",
                        "agents/**",
                    ),
                ),
            ),
        )
