import os
from dataclasses import dataclass
from pathlib import Path

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.vendor import BUILD_ARTIFACTS, GIT_ARTIFACTS, PY_ARTIFACTS, VendorDir

_SETUP = r"""uv_bin="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"
if [ ! -x "$uv_bin" ]; then
  error "steps: uv not found"
  exit 1
fi
if ! bin_exists npm; then
  fnm_bin="$HOME/.local/share/fnm/fnm"
  if [ -x "$fnm_bin" ]; then
    eval "$("$fnm_bin" env --shell bash)"
  fi
fi
if ! bin_exists npm; then
  error "steps: npm unavailable; node_fnm must run before Steps installation"
  exit 1
fi
install_config_dir "$DIR/config/steps" "$HOME/.local/share/steps" "steps"
(
  cd "$HOME/.local/share/steps"
  npm ci --omit=dev --ignore-scripts --no-audit --no-fund
)
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
                    exclude_dirs=GIT_ARTIFACTS | PY_ARTIFACTS | BUILD_ARTIFACTS | frozenset({"node_modules"}),
                    include_globs=(
                        "pyproject.toml",
                        "README.md",
                        "package.json",
                        "package-lock.json",
                        "src/**",
                        "skills/**",
                        "agents/**",
                        "extensions/**",
                    ),
                ),
            ),
        )
