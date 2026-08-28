import os
from pathlib import Path

import pytest

from dotgen import cli, macos_report
from dotgen.macos_report import (
    CONFIG_FILES,
    CONFLICTING_APPLICATIONS,
    LEGACY_DESTINATIONS,
    MANAGED_TREES,
    REQUIRED_APPLICATIONS,
    REQUIRED_COMMANDS,
    MacOSReportError,
    legacy_declarations,
    render_report,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _fixture_stage(stage: Path) -> None:
    for stage_relative, _host_relative, _check in CONFIG_FILES:
        _write(stage / stage_relative, f"stage:{stage_relative}\n")
    for stage_relative, _host_relative in MANAGED_TREES:
        _write(stage / stage_relative / "managed.txt", f"stage:{stage_relative}/managed.txt\n")


def _tree_state(root: Path) -> list[tuple[str, str, bytes | str]]:
    state: list[tuple[str, str, bytes | str]] = []
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            state.append((relative, "symlink", os.readlink(path)))
        elif path.is_dir():
            state.append((relative, "directory", ""))
        else:
            state.append((relative, "file", path.read_bytes()))
    return state


def test_report_covers_bounded_migration_state_without_writes_or_disclosure(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    home = tmp_path / "home"
    applications = tmp_path / "Applications"
    _fixture_stage(stage)

    for stage_relative, host_relative, check in CONFIG_FILES:
        if check == "manual":
            _write(home / host_relative, "FAKE-SECRET-SENTINEL\n")
        else:
            _write(home / host_relative, (stage / stage_relative).read_text())
    for stage_relative, host_relative in MANAGED_TREES:
        _write(home / host_relative / "managed.txt", (stage / stage_relative / "managed.txt").read_text())
        _write(home / host_relative / "runtime-extra.txt", "ignored\n")

    legacy_targets = tmp_path / "legacy"
    for host_relative in LEGACY_DESTINATIONS:
        destination = home / host_relative
        target = legacy_targets / host_relative.replace("/", "-").lstrip(".")
        _write(target, destination.read_text())
        destination.unlink()
        destination.symlink_to(target)

    (home / ".bash_profile").write_text("different\n")
    (home / ".tmux.conf").unlink()
    gitignore_target = legacy_targets / "gitignore_global"
    gitignore_target.unlink()
    starship_target = legacy_targets / "config-starship.toml"
    starship_content = starship_target.read_text()
    starship_target.unlink()
    starship_chain = legacy_targets / "starship-chain"
    _write(starship_chain, starship_content)
    starship_target.symlink_to(starship_chain)
    zed_keymap = home / ".config/zed/keymap.json"
    zed_keymap.unlink()
    zed_keymap.mkdir()
    unsafe_target = tmp_path / "unsafe-target"
    _write(unsafe_target, "must not be read\n")
    helix = home / ".config/helix/config.toml"
    helix.unlink()
    helix.symlink_to(unsafe_target)
    managed_target = tmp_path / "managed-target"
    _write(managed_target, "must not be read\n")
    managed = home / ".pi/agent/managed.txt"
    managed.unlink()
    managed.symlink_to(managed_target)
    managed_root_target = tmp_path / "managed-root-target"
    _write(managed_root_target / "managed.txt", "must not be read\n")
    angelini_root = home / "repos/pi-angelini"
    for child in angelini_root.iterdir():
        child.unlink()
    angelini_root.rmdir()
    angelini_root.symlink_to(managed_root_target)

    for name in ("ghostty", "git", "tcld", "ghosthub", "kwt", "btop", "cmux", "future-tool", "docker"):
        (home / ".config" / name).mkdir(parents=True, exist_ok=True)
    nested = home / ".config/ghostty/nested-candidate"
    nested.mkdir()

    for name in ("Ghostty.app", "Zed.app", "Docker.app"):
        (applications / name).mkdir(parents=True)

    _write(
        legacy_targets / "aliases",
        "alias kept='value'\nfunction wtgo-pi {\n}\nvalue() {\n}\nFAKE-SECRET-SENTINEL\n",
    )
    aliases = home / ".aliases"
    aliases.unlink()
    aliases.symlink_to(legacy_targets / "aliases")
    _write(home / ".bashrc", "plain() {\n}\n")

    before_home = _tree_state(home)
    before_stage = _tree_state(stage)
    output = render_report(
        stage,
        home=home,
        applications=applications,
        command_exists=lambda name: name in {"bash", "git"},
    )

    assert _tree_state(home) == before_home
    assert _tree_state(stage) == before_stage
    assert "different: alias.sh -> ~/.aliases (legacy symlink)" in output
    assert "different: config/bash/bash_profile -> ~/.bash_profile" in output
    assert "missing: config/tmux/tmux.conf -> ~/.tmux.conf" in output
    assert "type conflict: config/git/gitignore_global -> ~/.gitignore_global (legacy symlink)" in output
    assert "type conflict: config/starship/starship.toml -> ~/.config/starship.toml (legacy symlink)" in output
    assert "type conflict: config/zed/keymap.json -> ~/.config/zed/keymap.json" in output
    assert "type conflict: config/helix/config.toml -> ~/.config/helix/config.toml" in output
    assert "type conflict: config/pi/agent/managed.txt -> ~/.pi/agent/managed.txt" in output
    assert "type conflict: config/pi-angelini/managed.txt -> ~/repos/pi-angelini/managed.txt" in output
    assert "manual review: config/git/gitconfig -> ~/.gitconfig (legacy symlink)" in output
    assert "runtime-extra.txt" not in output
    assert "FAKE-SECRET-SENTINEL" not in output
    assert "must not be read" not in output
    assert "present: bash" in output
    assert "missing: delta" in output
    assert "present: Ghostty.app" in output
    assert "missing: OrbStack.app" in output
    assert "Supacode.app" not in output
    assert "conflict: Docker.app" in output
    assert "dropped: ~/.config/ghostty" in output
    assert "dropped: ~/.config/git" in output
    assert "~/.config/tcld" not in output
    assert "dropped: ~/.config/btop" in output
    assert "dropped: ~/.config/cmux" in output
    assert "unclassified: ~/.config/future-tool" in output
    assert "~/.config/docker" not in output
    assert "~/.config/ghosthub" not in output
    assert "~/.config/kwt" not in output
    assert "nested-candidate" not in output
    assert "~/.aliases:1 alias kept" in output
    assert "~/.aliases:2 function wtgo-pi" in output
    assert "~/.aliases:4 function value" in output


def test_report_constants_pin_selected_commands_applications_and_mapping() -> None:
    assert REQUIRED_COMMANDS == (
        "bash",
        "git",
        "delta",
        "jq",
        "yq",
        "fzf",
        "rg",
        "fd",
        "eza",
        "bat",
        "tree",
        "vim",
        "htop",
        "btop",
        "cloc",
        "gpg",
        "tmux",
        "mosh",
        "hx",
        "starship",
        "shellcheck",
        "zoxide",
        "kubectl",
        "helm",
        "k9s",
        "kubectx",
        "kubens",
        "kubie",
        "uv",
        "claude",
        "gh",
        "cargo",
        "rustc",
        "fnm",
        "node",
        "npm",
        "pi",
        "pi-sandbox",
        "psql",
        "go",
        "gcloud",
        "aws",
        "doppler",
        "docker",
    )
    assert REQUIRED_APPLICATIONS == ("Ghostty.app", "Zed.app", "OrbStack.app")
    assert CONFLICTING_APPLICATIONS == ("Docker.app",)
    assert CONFIG_FILES == (
        (".bashrc", ".bashrc", "exact"),
        ("alias.sh", ".aliases", "exact"),
        ("config/bash/bash_profile", ".bash_profile", "exact"),
        ("config/git/gitconfig", ".gitconfig", "manual"),
        ("config/git/gitignore_global", ".gitignore_global", "exact"),
        ("config/npm/npmrc", ".npmrc", "manual"),
        ("config/starship/starship.toml", ".config/starship.toml", "exact"),
        ("config/tmux/tmux.conf", ".tmux.conf", "exact"),
        ("config/helix/config.toml", ".config/helix/config.toml", "exact"),
        ("config/gh/config.yml", ".config/gh/config.yml", "exact"),
        ("config/aws/config", ".aws/config", "exact"),
        ("config/ghostty/config", "Library/Application Support/com.mitchellh.ghostty/config", "exact"),
        ("config/zed/settings.json", ".config/zed/settings.json", "exact"),
        ("config/zed/keymap.json", ".config/zed/keymap.json", "exact"),
        ("config/pi/sandbox/pi-macos.sb", ".config/pi/sandbox/pi-macos.sb", "exact"),
        ("config/pi/sandbox/pi-sandbox.sh", ".local/bin/pi-sandbox", "exact"),
        ("config/managed-settings/claude.json", ".claude/settings.json", "manual"),
        ("config/managed-settings/pi.json", ".pi/agent/settings.json", "manual"),
    )
    assert MANAGED_TREES == (("config/claude", ".claude"), ("config/pi/agent", ".pi/agent"), ("config/pi-angelini", "repos/pi-angelini"))
    assert frozenset({".aliases", ".bashrc", ".gitconfig", ".gitignore_global", ".config/starship.toml"}) == LEGACY_DESTINATIONS


def test_legacy_parser_keeps_duplicate_lines_and_hyphenated_functions() -> None:
    text = "alias same='first'\nalias same='second'\nname() {\n}\nfunction wtgo-pi\n"

    assert legacy_declarations(text, "~/.aliases") == [
        ("~/.aliases", 1, "alias", "same"),
        ("~/.aliases", 2, "alias", "same"),
        ("~/.aliases", 3, "function", "name"),
        ("~/.aliases", 5, "function", "wtgo-pi"),
    ]


def test_legacy_target_with_symlinked_ancestor_is_a_type_conflict(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    home = tmp_path / "home"
    _fixture_stage(stage)
    for stage_relative, host_relative, _check in CONFIG_FILES:
        _write(home / host_relative, (stage / stage_relative).read_text())
    for stage_relative, host_relative in MANAGED_TREES:
        _write(home / host_relative / "managed.txt", (stage / stage_relative / "managed.txt").read_text())

    target_root = tmp_path / "target-root"
    _write(target_root / "bashrc", "legacy\n")
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(target_root, target_is_directory=True)
    (home / ".bashrc").unlink()
    (home / ".bashrc").symlink_to(linked_parent / "bashrc")

    output = render_report(stage, home=home, applications=tmp_path / "Applications", command_exists=lambda _name: False)

    assert "type conflict: .bashrc -> ~/.bashrc (legacy symlink)" in output


def test_stage_walk_error_is_operational_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stage = tmp_path / "stage"
    home = tmp_path / "home"
    _fixture_stage(stage)
    for stage_relative, host_relative, _check in CONFIG_FILES:
        _write(home / host_relative, (stage / stage_relative).read_text())

    def failed_walk(_root: Path, *, followlinks: bool, onerror: object) -> list[tuple[str, list[str], list[str]]]:
        assert not followlinks
        assert callable(onerror)
        onerror(PermissionError("denied"))
        return []

    monkeypatch.setattr(macos_report.os, "walk", failed_walk)
    with pytest.raises(MacOSReportError, match="cannot inspect stage tree"):
        render_report(stage, home=home, applications=tmp_path / "Applications", command_exists=lambda _name: False)


def test_command_probe_uses_path_without_executing_bash_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    marker = tmp_path / "bash-env-ran"
    command = bin_dir / "present"
    bash_env = tmp_path / "bash-env"
    _write(command, "#!/bin/sh\nexit 0\n")
    command.chmod(0o755)
    _write(bash_env, f"touch {marker}\n")
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("BASH_ENV", str(bash_env))

    assert macos_report._command_exists("present")  # pyright: ignore[reportPrivateUsage]
    assert not macos_report._command_exists("missing")  # pyright: ignore[reportPrivateUsage]
    assert not marker.exists()


def test_report_rejects_invalid_stage_and_cli_reports_operational_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(MacOSReportError, match="stage is not a directory"):
        render_report(tmp_path / "missing-stage", home=tmp_path / "home")

    stage = tmp_path / "stage"
    expected = "focused report\n"

    def focused_report(path: Path) -> str:
        return expected if path == stage else "wrong\n"

    monkeypatch.setattr(cli, "render_report", focused_report)
    assert cli.main(["macos-report", "--stage", str(stage)]) == 0
    assert capsys.readouterr().out == expected

    def fail_report(_path: Path) -> str:
        raise MacOSReportError("invalid stage")

    monkeypatch.setattr(cli, "render_report", fail_report)
    with pytest.raises(SystemExit) as caught:
        cli.main(["macos-report", "--stage", str(stage)])
    assert caught.value.code == 2
    assert "invalid stage" in capsys.readouterr().err
