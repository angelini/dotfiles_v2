import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotgen.bash import section
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS

if TYPE_CHECKING:
    from dotgen.environment import Environment

_SETTINGS: dict = {
    "edit_predictions": {"provider": "none"},
    "show_edit_predictions": False,
    "disable_ai": True,
    "colorize_brackets": True,
    "helix_mode": False,
    "current_line_highlight": "gutter",
    "inline_code_actions": False,
    "hover_popover_enabled": True,
    "auto_signature_help": True,
    "autosave": "on_focus_change",
    "restore_on_startup": "empty_tab",
    "show_wrap_guides": True,
    "wrap_guides": [100],
    "buffer_font_family": "Ubuntu",
    "buffer_font_size": 14.0,
    "ui_font_size": 16.0,
    "scroll_beyond_last_line": "vertical_scroll_margin",
    "excerpt_context_lines": 3,
    "double_click_in_multibuffer": "open",
    "autoscroll_on_clicks": True,
    "agent_servers": {"claude-acp": {"type": "registry"}},
    "agent": {
        "dock": "right",
        "button": True,
        "favorite_models": [],
        "model_parameters": [],
    },
    "git_panel": {"dock": "left", "button": True},
    "project_panel": {
        "dock": "left",
        "hide_root": True,
        "indent_size": 18.0,
        "entry_spacing": "comfortable",
    },
    "outline_panel": {"dock": "left", "button": False},
    "collaboration_panel": {"dock": "right", "button": False},
    "debugger": {"button": False},
    "title_bar": {"show_menus": False, "show_sign_in": False},
    "inlay_hints": {
        "enabled": True,
        "show_type_hints": False,
        "show_background": False,
    },
    "toolbar": {
        "selections_menu": True,
        "code_actions": False,
        "agent_review": True,
        "quick_actions": True,
    },
    "minimap": {
        "show": "never",
        "display_in": "active_editor",
        "thumb_border": "left_open",
    },
    "gutter": {
        "min_line_number_digits": 4,
        "runnables": False,
        "folds": False,
        "breakpoints": False,
    },
    "sticky_scroll": {"enabled": True},
    "which_key": {"enabled": False},
    "session": {"trust_all_worktrees": True},
    "git": {
        "blame": {"show_avatar": True},
        "inline_blame": {"enabled": False},
        "enable_diff": True,
        "enable_status": True,
    },
    "telemetry": {"diagnostics": True, "metrics": True},
    "theme": {
        "mode": "system",
        "light": "Modus Operandi Deuteranopia",
        "dark": "One Dark",
    },
    "file_types": {
        "Helm": ["**/charts/**/*.yaml", "**/*.tpl"],
        "Shell Script": ["**/terraform/tf"],
    },
}

_KEYMAP: list = [
    {
        "context": "Workspace",
        "bindings": {"cmd-w": "editor::ToggleFocus"},
    },
    {"unbind": {"alt-cmd-i": "dev::ToggleInspector"}},
]

_SETTINGS_JSON = json.dumps(_SETTINGS, indent=2) + "\n"
_KEYMAP_JSON = json.dumps(_KEYMAP, indent=2) + "\n"

_SETUP_BY_OS: dict[OS, str] = {
    OS.MACOS: "install_cask zed\n",
    OS.FEDORA: "install_script zed https://zed.dev/install.sh\n",
    OS.DEBIAN: "install_script zed https://zed.dev/install.sh\n",
}

_SETUP_TAIL = (
    'install_config "$DIR/config/zed/settings.json" "$HOME/.config/zed/settings.json"\n'
    'install_config "$DIR/config/zed/keymap.json" "$HOME/.config/zed/keymap.json"\n'
)


@dataclass(frozen=True)
class Zed:
    name: str = "zed"

    def applies_to(self, env: "Environment") -> bool:
        return True

    def render(self, env: "Environment") -> Fragment:
        body = _SETUP_BY_OS[env.os] + _SETUP_TAIL
        return Fragment(
            setup=section("zed", body),
            configs=(
                ConfigFile(dest="zed/settings.json", content=_SETTINGS_JSON),
                ConfigFile(dest="zed/keymap.json", content=_KEYMAP_JSON),
            ),
        )
