import json
import os
from pathlib import Path
from typing import Literal, NoReturn, cast

ManagedSettingsName = Literal["claude", "pi"]


def _agent_config_root() -> Path:
    configured = os.environ.get("DOTGEN_AGENT_CONFIG_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4] / "agent-config"


def _reject_nonfinite(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON value: {value}")


def _json_object(path: Path, description: str) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(), parse_constant=_reject_nonfinite)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid {description} JSON at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{description} must be a JSON object: {path}")
    return cast(dict[str, object], data)


def managed_settings(name: ManagedSettingsName) -> str:
    if name not in ("claude", "pi"):
        raise ValueError(f"unsupported managed settings name: {name}")
    path = _agent_config_root() / "settings" / f"{name}.managed.json"
    return json.dumps(_json_object(path, "managed settings"), indent=2, sort_keys=True) + "\n"


def pi_models() -> str:
    path = _agent_config_root() / "pi" / "agent" / "models.json"
    return json.dumps(_json_object(path, "Pi models"), indent=2) + "\n"
