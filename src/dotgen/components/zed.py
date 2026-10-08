import json
from dataclasses import dataclass
from typing import Any

from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS, EnvironmentRole

_SETTINGS: dict[str, Any] = {
    "cli_default_open_behavior": "new_window",
    "diff_view_style": "unified",
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
    "buffer_font_family": ".ZedMono",
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
        "Helm": [
            "**/charts/*/templates/*.yaml",
            "**/charts/*/templates/**/*.yaml",
            "**/charts/*/templates/*.yml",
            "**/charts/*/templates/**/*.yml",
            "**/charts/*/templates/*.tpl",
            "**/charts/*/templates/**/*.tpl",
            "**/charts/*/values*.yaml",
            "**/charts/*/values*.yml",
            "**/deploy/helm/templates/*.yaml",
            "**/deploy/helm/templates/**/*.yaml",
            "**/deploy/helm/templates/*.yml",
            "**/deploy/helm/templates/**/*.yml",
            "**/deploy/helm/templates/*.tpl",
            "**/deploy/helm/templates/**/*.tpl",
            "**/deploy/helm/values*.yaml",
            "**/deploy/helm/values*.yml",
        ],
        "Shell Script": ["**/terraform/tf"],
    },
}

_KEYMAP_BY_OS: dict[OS, list[dict[str, Any]]] = {
    OS.CACHYOS: [
        {
            "context": "Workspace",
            "bindings": {"super-w": "editor::ToggleFocus"},
        },
        {"unbind": {"alt-super-i": "dev::ToggleInspector"}},
    ],
    OS.MACOS: [
        {
            "context": "Workspace",
            "bindings": {"cmd-w": "editor::ToggleFocus"},
        },
        {"unbind": {"alt-cmd-i": "dev::ToggleInspector"}},
    ],
}

_SETTINGS_JSON = json.dumps(_SETTINGS, indent=2) + "\n"
_KEYMAP_JSON_BY_OS = {os: json.dumps(keymap, indent=2) + "\n" for os, keymap in _KEYMAP_BY_OS.items()}

_SETUP_BY_OS: dict[OS, str] = {
    OS.CACHYOS: (
        "install_package zed\n"
        'if ! bin_exists zeditor; then error "Zed package installed without zeditor CLI"; exit 1; fi\n'
        'install_config "$DIR/config/zed/settings.json" "${XDG_CONFIG_HOME:-$HOME/.config}/zed/settings.json"\n'
        'install_config "$DIR/config/zed/keymap.json" "${XDG_CONFIG_HOME:-$HOME/.config}/zed/keymap.json"\n'
    ),
    OS.MACOS: (
        "install_cask zed\n"
        'install_config "$DIR/config/zed/settings.json" "$HOME/.config/zed/settings.json"\n'
        'install_config "$DIR/config/zed/keymap.json" "$HOME/.config/zed/keymap.json"\n'
    ),
}


@dataclass(frozen=True)
class Zed:
    name: str = "zed"

    def applies_to(self, env: Environment) -> bool:
        return env.role is EnvironmentRole.WORKSTATION and env.os in _SETUP_BY_OS

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP_BY_OS[env.os],
            configs=(
                ConfigFile(dest="zed/settings.json", content=_SETTINGS_JSON),
                ConfigFile(dest="zed/keymap.json", content=_KEYMAP_JSON_BY_OS[env.os]),
            ),
        )
