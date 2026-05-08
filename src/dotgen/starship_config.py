import tomli_w

_DISABLED_MODULES: tuple[str, ...] = ("gcloud", "aws", "docker_context", "dotnet")


def render_starship_toml() -> str:
    config: dict[str, object] = {
        "format": "$directory$git_branch$git_status$kubernetes$character",
        "add_newline": False,
        "kubernetes": {
            "disabled": False,
            "format": "[$symbol$context( \\($namespace\\))]($style) ",
            "symbol": "⎈ ",
            "contexts": [{"context_pattern": ".*prod.*", "style": "bold red"}],
        },
    }
    for module in _DISABLED_MODULES:
        config[module] = {"disabled": True}
    return tomli_w.dumps(config)
