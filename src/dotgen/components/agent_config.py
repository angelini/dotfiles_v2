import os
from pathlib import Path


def _agent_config_root() -> Path:
    configured = os.environ.get("DOTGEN_AGENT_CONFIG_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4] / "agent-config"
