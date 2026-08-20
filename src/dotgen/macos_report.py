import filecmp
import os
import re
import shutil
import stat
from collections.abc import Callable
from pathlib import Path

CONFIG_FILES: tuple[tuple[str, str, str], ...] = (
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

MANAGED_TREES: tuple[tuple[str, str], ...] = (
    ("config/claude", ".claude"),
    ("config/pi/agent", ".pi/agent"),
    ("config/pi-angelini", "repos/pi-angelini"),
)

LEGACY_DESTINATIONS = frozenset({".aliases", ".bashrc", ".gitconfig", ".gitignore_global", ".config/starship.toml"})

REQUIRED_COMMANDS = (
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

REQUIRED_APPLICATIONS = ("Ghostty.app", "Zed.app", "Supacode.app", "OrbStack.app")
CONFLICTING_APPLICATIONS = ("Docker.app",)

_REVIEW_CONFIG_DIRS: frozenset[str] = frozenset()
_EXCLUDED_CONFIG_DIRS = frozenset({"1Password", "argocd", "configstore", "docker", "dotgen", "gcloud", "gh", "ghosthub", "helix", "hister", "kwt", "orbstack", "pi", "tcld", "zed"})
_DROPPED_CONFIG_DIRS = frozenset({"btop", "cmux", "ghostty", "git", "htop", "hunk", "kitty", "opencode", "wt", "zellij"})

_ALIAS_RE = re.compile(r"^\s*alias\s+([A-Za-z_][A-Za-z0-9_-]*)=", re.MULTILINE)
_NAMED_FUNCTION_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*\(\)\s*\{", re.MULTILINE)
_FUNCTION_RE = re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_-]*)(?:\s*\(\))?(?:\s*\{)?", re.MULTILINE)

CommandExists = Callable[[str], bool]


class MacOSReportError(RuntimeError):
    pass


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise MacOSReportError(f"cannot inspect {path}: {error}") from error


def _stage_file(stage: Path, relative: str) -> Path:
    path = stage / relative
    info = _lstat(path)
    if info is None or not stat.S_ISREG(info.st_mode):
        raise MacOSReportError(f"stage path is not a regular file: {path}")
    return path


def _host_file(path: Path, *, allow_legacy_symlink: bool) -> tuple[str, Path | None, bool]:
    info = _lstat(path)
    if info is None:
        return "missing", None, False
    if stat.S_ISREG(info.st_mode):
        return "regular", path, False
    if not stat.S_ISLNK(info.st_mode) or not allow_legacy_symlink:
        return "type conflict", None, False
    try:
        link = os.readlink(path)
    except OSError as error:
        raise MacOSReportError(f"cannot inspect {path}: {error}") from error
    target = Path(link) if os.path.isabs(link) else path.parent / link
    if any((parent_info := _lstat(parent)) is not None and stat.S_ISLNK(parent_info.st_mode) for parent in target.parents):
        return "type conflict", None, True
    target_info = _lstat(target)
    if target_info is None or not stat.S_ISREG(target_info.st_mode):
        return "type conflict", None, True
    return "regular", target, True


def _managed_host_file(root: Path, relative: Path) -> tuple[str, Path | None, bool]:
    current = root
    for part in relative.parts[:-1]:
        info = _lstat(current)
        if info is None:
            return "missing", None, False
        if not stat.S_ISDIR(info.st_mode):
            return "type conflict", None, False
        current /= part
    parent_info = _lstat(current)
    if parent_info is None:
        return "missing", None, False
    if not stat.S_ISDIR(parent_info.st_mode):
        return "type conflict", None, False
    return _host_file(current / relative.name, allow_legacy_symlink=False)


def _stage_tree_files(root: Path) -> tuple[Path, ...]:
    info = _lstat(root)
    if info is None or not stat.S_ISDIR(info.st_mode):
        raise MacOSReportError(f"stage path is not a directory: {root}")

    def fail_walk(error: OSError) -> None:
        raise MacOSReportError(f"cannot inspect stage tree {root}: {error}") from error

    found: list[Path] = []
    for current, directories, files in os.walk(root, followlinks=False, onerror=fail_walk):
        current_path = Path(current)
        for name in directories:
            child = current_path / name
            child_info = _lstat(child)
            if child_info is None or not stat.S_ISDIR(child_info.st_mode):
                raise MacOSReportError(f"stage tree contains a non-directory entry: {child}")
        for name in files:
            child = current_path / name
            child_info = _lstat(child)
            if child_info is None or not stat.S_ISREG(child_info.st_mode):
                raise MacOSReportError(f"stage tree contains a non-file entry: {child}")
            found.append(child.relative_to(root))
    return tuple(sorted(found))


def config_findings(stage: Path, home: Path) -> list[tuple[str, str, str, bool]]:
    findings: list[tuple[str, str, str, bool]] = []
    for stage_relative, host_relative, check in CONFIG_FILES:
        stage_path = _stage_file(stage, stage_relative)
        kind, compare_path, legacy = _host_file(home / host_relative, allow_legacy_symlink=host_relative in LEGACY_DESTINATIONS)
        if kind != "regular":
            status = kind
        elif check == "manual":
            status = "manual review"
        else:
            if compare_path is None:
                raise MacOSReportError(f"cannot compare host path: {home / host_relative}")
            status = "match" if filecmp.cmp(stage_path, compare_path, shallow=False) else "different"
        findings.append((status, stage_relative, f"~/{host_relative}", legacy))
    for stage_relative, host_relative in MANAGED_TREES:
        stage_root = stage / stage_relative
        host_root = home / host_relative
        for relative in _stage_tree_files(stage_root):
            kind, compare_path, _legacy = _managed_host_file(host_root, relative)
            if kind != "regular":
                status = kind
            else:
                if compare_path is None:
                    raise MacOSReportError(f"cannot compare host path: {host_root / relative}")
                status = "match" if filecmp.cmp(stage_root / relative, compare_path, shallow=False) else "different"
            findings.append((status, f"{stage_relative}/{relative}", f"~/{host_relative}/{relative}", False))
    return findings


def host_config_candidates(home: Path) -> list[tuple[str, str]]:
    root = home / ".config"
    info = _lstat(root)
    if info is None:
        return []
    if not stat.S_ISDIR(info.st_mode):
        raise MacOSReportError(f"host config root is not a directory: {root}")
    try:
        names = sorted(entry.name for entry in os.scandir(root) if entry.is_dir(follow_symlinks=False))
    except OSError as error:
        raise MacOSReportError(f"cannot inspect {root}: {error}") from error
    candidates: list[tuple[str, str]] = []
    for name in names:
        if name in _EXCLUDED_CONFIG_DIRS:
            continue
        if name in _REVIEW_CONFIG_DIRS:
            candidates.append(("review", name))
        elif name in _DROPPED_CONFIG_DIRS:
            candidates.append(("dropped", name))
        else:
            candidates.append(("unclassified", name))
    return candidates


def legacy_declarations(text: str, source: str) -> list[tuple[str, int, str, str]]:
    declarations: list[tuple[str, int, str, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in (("alias", _ALIAS_RE), ("function", _NAMED_FUNCTION_RE), ("function", _FUNCTION_RE)):
            match = pattern.match(line)
            if match is not None:
                declarations.append((source, line_number, kind, match.group(1)))
                break
    return declarations


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _legacy_file_declarations(home: Path, relative: str) -> list[tuple[str, int, str, str]]:
    kind, path, _legacy = _host_file(home / relative, allow_legacy_symlink=True)
    if kind != "regular":
        return []
    if path is None:
        raise MacOSReportError(f"cannot read ~/{relative}")
    try:
        return legacy_declarations(path.read_text(), f"~/{relative}")
    except (OSError, UnicodeError) as error:
        raise MacOSReportError(f"cannot read ~/{relative}: {error}") from error


def render_report(
    stage: Path,
    *,
    home: Path | None = None,
    applications: Path = Path("/Applications"),
    command_exists: CommandExists = _command_exists,
) -> str:
    stage_info = _lstat(stage)
    if stage_info is None or not stat.S_ISDIR(stage_info.st_mode):
        raise MacOSReportError(f"stage is not a directory: {stage}")
    inspected_home = home if home is not None else Path.home()
    lines = ["macOS migration report", "", "Config:"]
    for status, stage_path, host_path, legacy in config_findings(stage, inspected_home):
        annotation = " (legacy symlink)" if legacy else ""
        lines.append(f"  {status}: {stage_path} -> {host_path}{annotation}")

    lines.extend(("", "Commands:"))
    for name in REQUIRED_COMMANDS:
        status = "present" if command_exists(name) else "missing"
        lines.append(f"  {status}: {name}")

    lines.extend(("", "Applications:"))
    for name in REQUIRED_APPLICATIONS:
        status = "present" if (applications / name).is_dir() else "missing"
        lines.append(f"  {status}: {name}")
    for name in CONFLICTING_APPLICATIONS:
        status = "conflict" if (applications / name).is_dir() else "absent"
        lines.append(f"  {status}: {name}")

    lines.extend(("", "Host config directories:"))
    candidates = host_config_candidates(inspected_home)
    if candidates:
        lines.extend(f"  {classification}: ~/.config/{name}" for classification, name in candidates)
    else:
        lines.append("  none")

    lines.extend(("", "Legacy shell declarations:"))
    declarations = _legacy_file_declarations(inspected_home, ".aliases") + _legacy_file_declarations(inspected_home, ".bashrc")
    if declarations:
        lines.extend(f"  {source}:{line_number} {kind} {name}" for source, line_number, kind, name in declarations)
    else:
        lines.append("  none")
    return "\n".join(lines) + "\n"
