import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from dotgen.components.agent_config import _agent_config_root, managed_settings, pi_models  # pyright: ignore[reportPrivateUsage]
from dotgen.environment import Environment
from dotgen.fragment import ConfigFile, Fragment
from dotgen.types import OS
from dotgen.vendor import GIT_ARTIFACTS, NODE_ARTIFACTS, PY_ARTIFACTS, VendorDir

_WEB_SEARCH_JSON = json.dumps({"provider": "exa"}, indent=2) + "\n"

_RESOURCE_ROOT = Path(__file__).resolve().parents[1] / "resources" / "pi_agent"


def _resource_text(relative_path: str) -> str:
    return (_RESOURCE_ROOT / relative_path).read_text()


_PI_LAUNCHER_SH = _resource_text("pi.sh")
_PLANNOTATOR_JSON = _resource_text("plannotator.json")


def _pi_angelini_root() -> Path:
    configured = os.environ.get("DOTGEN_PI_ANGELINI_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4] / "pi-angelini"


_PI_PACKAGES = (
    "@earendil-works/pi-coding-agent",
    "pi-lens",
    "pi-mcp-adapter",
    "pi-subagents",
    "pi-simplify",
    "@plannotator/pi-extension",
    "@dreki-gg/pi-context7",
    "@juicesharp/rpiv-ask-user-question",
    "@juicesharp/rpiv-btw",
    "@juicesharp/rpiv-todo",
    "@samfp/pi-memory",
    "@vanillagreen/pi-web-tools",
)


@dataclass(frozen=True)
class _SandboxHomePolicy:
    writable_dirs: tuple[str, ...]
    readonly_dirs: tuple[str, ...]
    readonly_files: tuple[str, ...]
    hidden_dirs: tuple[str, ...]
    hidden_files: tuple[str, ...]


SANDBOX_HOME_POLICY = _SandboxHomePolicy(
    writable_dirs=(
        "repos",
        ".pi",
        ".pi-lens",
        ".cache",
        ".config",
        ".cargo",
        ".local/share",
        ".local/state",
        ".npm",
        "go",
    ),
    readonly_dirs=(
        "bin",
        ".cargo/bin",
        ".local/bin",
        ".local/share/fnm",
        ".local/share/go",
        ".local/state/fnm_multishells",
        ".rustup",
    ),
    readonly_files=(
        ".gitconfig",
        ".gitignore_global",
        ".config/git/config",
        ".config/gcloud/application_default_credentials.json",
        ".config/pi/sandbox/pi-macos.sb",
    ),
    hidden_dirs=(
        ".ssh",
        ".gnupg",
        ".aws",
        ".azure",
        ".config/dotgen",
        ".kube",
        ".claude",
        ".local/share/stinkpot",
    ),
    hidden_files=(
        ".docker/config.json",
        ".config/gh/hosts.yml",
        ".config/git/credentials",
        ".config/helm/registry/config.json",
        ".config/helm/repositories.yaml",
        ".git-credentials",
        ".netrc",
        ".npmrc",
        ".pypirc",
        ".cargo/credentials",
        ".cargo/credentials.toml",
        ".bash_history",
        ".zsh_history",
        ".python_history",
    ),
)


def _bwrap_home_policy(policy: _SandboxHomePolicy) -> str:
    args = [f'--bind "$HOME/{path}" "$HOME/{path}"' for path in policy.writable_dirs]
    args.extend(f'--ro-bind "$HOME/{path}" "$HOME/{path}"' for path in policy.readonly_dirs)
    args.extend(f'--ro-bind-try "$HOME/{path}" "$HOME/{path}"' for path in policy.readonly_files)
    args.extend(f'--tmpfs "$HOME/{path}"' for path in policy.hidden_dirs)
    args.extend(f'--ro-bind /dev/null "$HOME/{path}"' for path in policy.hidden_files)
    return "\n".join(f"    {arg} \\" for arg in args)


def _sandbox_home_dirs_sh(policy: _SandboxHomePolicy) -> str:
    paths = dict.fromkeys((*policy.writable_dirs, *policy.readonly_dirs))
    for path in policy.readonly_files:
        parent, separator, _ = path.rpartition("/")
        if separator:
            paths.setdefault(parent, None)
    return "\n".join(f'    "$HOME/{path}" \\' for path in paths)


def _seatbelt_filters(paths: tuple[str, ...], *, literal: bool = False) -> str:
    kind = "literal" if literal else "subpath"
    return "\n".join(f'  ({kind} (string-append (param "HOME") "/{path}"))' for path in paths)


_pi_sandbox_sh_template = r"""#!/usr/bin/env bash
set -euo pipefail

_die() {
  printf 'pi-sandbox: %s\n' "$*" >&2
  exit 2
}

_load_dotgen_secrets() {
  local f="${XDG_CONFIG_HOME:-$HOME/.config}/dotgen/secrets.env"
  [ -r "$f" ] || return 0
  set -a
  # shellcheck disable=SC1090
  source "$f"
  set +a
}

_resolve_path() {
  cd "$1" 2>/dev/null && pwd -P
}

_prepare_jiti_cache() {
  local cache="$1" cache_parent real_cache real_cache_parent real_home
  real_home="$(_resolve_path "$HOME")" || _die "cannot resolve home directory: $HOME"
  cache_parent="${cache%/*}"

  [ ! -L "$cache_parent" ] || _die "refusing symlinked Pi sandbox cache directory: $cache_parent"
  [ ! -e "$cache_parent" ] || [ -d "$cache_parent" ] || _die "Pi sandbox cache path is not a directory: $cache_parent"
  mkdir -p "$cache_parent"
  chmod 0700 "$cache_parent"
  real_cache_parent="$(_resolve_path "$cache_parent")" || _die "cannot resolve Pi sandbox cache directory: $cache_parent"
  [ "$real_cache_parent" = "$real_home/.pi-sandbox-cache" ] || _die "Pi sandbox cache directory escapes expected path: $cache_parent"

  [ ! -L "$cache" ] || _die "refusing symlinked Jiti cache directory: $cache"
  [ ! -e "$cache" ] || [ -d "$cache" ] || _die "Jiti cache path is not a directory: $cache"
  mkdir -p "$cache"
  chmod 0700 "$cache"
  real_cache="$(_resolve_path "$cache")" || _die "cannot resolve Jiti cache directory: $cache"
  [ "$real_cache" = "$real_cache_parent/jiti" ] || _die "Jiti cache directory escapes expected path: $cache"
  printf '%s\n' "$real_cache"
}

_prepare_herdr_clipboard_images() {
  local path="$1" owner real_path
  [ ! -L "$path" ] || _die "refusing symlinked Herdr clipboard image directory: $path"
  [ ! -e "$path" ] || [ -d "$path" ] || _die "Herdr clipboard image path is not a directory: $path"
  mkdir -p "$path"
  owner="$(stat -c %u "$path")" || _die "cannot inspect Herdr clipboard image directory: $path"
  [ "$owner" = "$(id -u)" ] || _die "Herdr clipboard image directory has unexpected owner: $path"
  chmod 0700 "$path"
  real_path="$(_resolve_path "$path")" || _die "cannot resolve Herdr clipboard image directory: $path"
  [ "$real_path" = "$path" ] || _die "Herdr clipboard image directory escapes expected path: $path"
  printf '%s\n' "$real_path"
}

_fnm_default_bin() {
  local bin="${FNM_DIR:-$HOME/.local/share/fnm}/aliases/default/bin"
  [ -x "$bin/node" ] || return 1
  printf '%s\n' "$bin"
}

main() {
  local repos="$HOME/repos" memory_dir="$HOME/.pi/memory"
  local cwd real_repos node_bin pi_bin transformers_cache transformers_cache_target
  cwd="$(_resolve_path "$PWD")" || _die "cannot resolve current directory: $PWD"
  real_repos="$(_resolve_path "$repos")" || _die "missing repos directory: $repos"
  case "$cwd" in
    "$real_repos"|"$real_repos"/*) ;;
    *) _die "run pi-sandbox from within $repos" ;;
  esac

  # fnm's use-on-cd repoints this shell's node version for the rest of its life, and npm
  # globals are per-version, so pin the sandbox to the version the pi packages were installed for
  node_bin="$(_fnm_default_bin)" || _die "fnm default node installation not found"
  PATH="$node_bin:$PATH"

  pi_bin="$(command -v pi)" || _die "pi binary not found in $node_bin"
  [ -x "$pi_bin" ] || _die "pi binary is not executable: $pi_bin"
  transformers_cache="$memory_dir/transformers-cache"
  transformers_cache_target="$(npm root -g)/@samfp/pi-memory/node_modules/@xenova/transformers/.cache"
  mkdir -p \
__SANDBOX_HOME_DIRS__
    "$transformers_cache" \
    "$transformers_cache_target"
  [ -e "$HOME/.config/git/config" ] || : > "$HOME/.config/git/config"

  _load_dotgen_secrets

  case "$(uname -s)" in
    Darwin) _run_macos "$pi_bin" "$transformers_cache_target" "$@" ;;
    Linux) _run_linux "$pi_bin" "$transformers_cache" "$transformers_cache_target" "$@" ;;
    *) _die "unsupported OS: $(uname -s)" ;;
  esac
}

_run_macos() {
  local pi_bin="$1" transformers_cache_target="$2"
  local profile="$HOME/.config/pi/sandbox/pi-macos.sb" tmpdir
  shift 2
  [ -r "$profile" ] || _die "missing sandbox profile: $profile"
  tmpdir="$(_resolve_path "${TMPDIR:-/tmp}")" || _die "cannot resolve temporary directory: ${TMPDIR:-/tmp}"
  exec env -i \
    "HOME=$HOME" \
    "PATH=${PATH:-/usr/bin:/bin}" \
    "SHELL=${SHELL:-/bin/bash}" \
    "TERM=${TERM:-xterm-256color}" \
    "LANG=${LANG:-C.UTF-8}" \
    "TMPDIR=$tmpdir" \
    "DOTGEN_PI_SANDBOX=1" \
    "JITI_FS_CACHE=1" \
    "GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT:-${GCP_PROJECT_ID:-}}" \
    "GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION:-europe-west4}" \
    "EXA_API_KEY=${EXA_API_KEY:-}" \
    "CONTEXT7_API_KEY=${CONTEXT7_API_KEY:-}" \
    sandbox-exec \
    -D "HOME=$HOME" \
    -D "HOME_PARENT=$(dirname "$HOME")" \
    -D "TMPDIR=$tmpdir" \
    -D "TRANSFORMERS_CACHE=$transformers_cache_target" \
    -f "$profile" \
    "$pi_bin" "$@"
}

_run_linux() {
  local pi_bin="$1" transformers_cache="$2" transformers_cache_target="$3"
  local herdr_clipboard_images
  local jiti_cache="$HOME/.pi-sandbox-cache/jiti" runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  shift 3
  herdr_clipboard_images="/tmp/herdr-clipboard-images-$(id -u)"
  command -v bwrap >/dev/null 2>&1 || _die "bwrap is required"
  herdr_clipboard_images="$(_prepare_herdr_clipboard_images "$herdr_clipboard_images")"
  jiti_cache="$(_prepare_jiti_cache "$jiti_cache")"
  exec env -i \
    "HOME=$HOME" \
    "PATH=${PATH:-/usr/bin:/bin}" \
    "SHELL=${SHELL:-/bin/bash}" \
    "TERM=${TERM:-xterm-256color}" \
    "LANG=${LANG:-C.UTF-8}" \
    "DOTGEN_PI_SANDBOX=1" \
    "JITI_FS_CACHE=1" \
    "GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT:-${GCP_PROJECT_ID:-}}" \
    "GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION:-europe-west4}" \
    "EXA_API_KEY=${EXA_API_KEY:-}" \
    "CONTEXT7_API_KEY=${CONTEXT7_API_KEY:-}" \
    bwrap \
    --unshare-user-try \
    --unshare-ipc \
    --unshare-pid \
    --die-with-parent \
    --proc /proc \
    --dev-bind /dev /dev \
    --tmpfs /tmp \
    --ro-bind "$herdr_clipboard_images" "$herdr_clipboard_images" \
    --bind "$jiti_cache" /tmp/jiti \
    --dir /run \
    --dir /run/user \
    --dir "$runtime_dir" \
    --dir "$HOME" \
__BWRAP_HOME_POLICY__
    --bind "$transformers_cache" "$transformers_cache_target" \
    --ro-bind-try "$runtime_dir/fnm_multishells" "$runtime_dir/fnm_multishells" \
    --ro-bind /usr /usr \
    --ro-bind /bin /bin \
    --ro-bind-try /lib /lib \
    --ro-bind-try /lib64 /lib64 \
    --ro-bind /etc /etc \
    --setenv HOME "$HOME" \
    --setenv XDG_RUNTIME_DIR "$runtime_dir" \
    --chdir "$PWD" \
    "$pi_bin" "$@"
}

main "$@"
"""

_pi_macos_sb_template = r"""(version 1)
(deny default)

(allow process*)
(allow signal)
(allow network*)
(allow network-outbound
  (literal "/private/var/run/mDNSResponder"))
(allow sysctl*)
(allow mach-lookup)
(allow file-ioctl)

(allow file-read-data (literal "/"))
(allow file-read* file-write*
  (subpath (param "TMPDIR"))
  (subpath "/tmp")
  (subpath "/private/tmp"))
(allow file-read* file-write-data
  (literal "/dev/null")
  (literal "/dev/zero"))
(allow file-read-data file-test-existence file-write-data
  (subpath "/dev/fd"))

(allow file-read*
  (subpath "/bin")
  (subpath "/sbin")
  (subpath "/usr/bin")
  (subpath "/usr/sbin")
  (subpath "/usr/lib")
  (subpath "/usr/share")
  (subpath "/System/Library")
  (subpath "/Library")
  (subpath "/opt/homebrew")
  (subpath "/usr/local")
  (subpath "/private/etc")
  (subpath "/private/var/db/timezone")
  (subpath "/private/var/db/dyld")
  (subpath "/private/var/select")
__MACOS_RW_DIRS__
__MACOS_RO_DIRS__
__MACOS_RO_FILES__)

(allow file-write*
__MACOS_RW_DIRS__)

(allow file-read-metadata
  (literal "/")
  (literal "/etc")
  (literal "/var")
  (literal (param "HOME_PARENT"))
  (subpath (param "HOME"))
  (literal "/private")
  (literal "/private/tmp")
  (literal "/private/var")
  (literal "/private/var/tmp"))

(deny file-write* (with no-report)
__MACOS_RO_DIRS__
__MACOS_RO_FILES__)

(allow file-read* file-write*
  (subpath (param "TRANSFORMERS_CACHE")))

(deny file-read* file-write* (with no-report)
__MACOS_HIDDEN_DIRS__
__MACOS_HIDDEN_FILES__)
"""

_PI_SANDBOX_SH = _pi_sandbox_sh_template.replace("__SANDBOX_HOME_DIRS__", _sandbox_home_dirs_sh(SANDBOX_HOME_POLICY)).replace("__BWRAP_HOME_POLICY__", _bwrap_home_policy(SANDBOX_HOME_POLICY))
_PI_MACOS_SB = (
    _pi_macos_sb_template.replace("__MACOS_RW_DIRS__", _seatbelt_filters(SANDBOX_HOME_POLICY.writable_dirs))
    .replace("__MACOS_RO_DIRS__", _seatbelt_filters(SANDBOX_HOME_POLICY.readonly_dirs))
    .replace(
        "__MACOS_RO_FILES__",
        _seatbelt_filters(SANDBOX_HOME_POLICY.readonly_files, literal=True),
    )
    .replace("__MACOS_HIDDEN_DIRS__", _seatbelt_filters(SANDBOX_HOME_POLICY.hidden_dirs))
    .replace(
        "__MACOS_HIDDEN_FILES__",
        _seatbelt_filters(SANDBOX_HOME_POLICY.hidden_files, literal=True),
    )
)

_ALIAS = """\
pi() {
  pi-sandbox "$@"
}

pi-unsafe() {
  command pi "$@"
}
"""

_SETUP_BASE = (
    "install_npm_global "
    + shlex.join(_PI_PACKAGES)
    + r"""
ensure_dir "$HOME/.pi/agent"
ensure_dir "$HOME/.config/pi/sandbox"
ensure_dir "$HOME/.local/bin"
install_config_dir "$DIR/config/pi/agent" "$HOME/.pi/agent" "pi-agent" "settings.json"
install_json_patch "$DIR/config/managed-settings/pi.json" "$HOME/.pi/agent/settings.json" 0600
install_config "$DIR/config/pi/sandbox/pi-macos.sb" "$HOME/.config/pi/sandbox/pi-macos.sb"
install -m 0755 "$DIR/config/pi/launcher/pi.sh" "$HOME/.local/bin/pi"
install -m 0755 "$DIR/config/pi/sandbox/pi-sandbox.sh" "$HOME/.local/bin/pi-sandbox"

install_config_dir "$DIR/config/pi-angelini" "$HOME/repos/pi-angelini"
"""
)


def _setup_for(env: Environment) -> str:
    parts: list[str] = []
    if env.os is OS.DEBIAN:
        parts.append("install_package bubblewrap")
    parts.append(_SETUP_BASE)
    return "\n".join(parts)


@dataclass(frozen=True)
class PiAgent:
    name: str = "pi_agent"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_setup_for(env),
            alias=_ALIAS,
            configs=(
                ConfigFile(dest="managed-settings/pi.json", content=managed_settings("pi"), mode=0o600),
                ConfigFile(dest="pi/agent/models.json", content=pi_models(), mode=0o600),
                ConfigFile(dest="pi/agent/web-search.json", content=_WEB_SEARCH_JSON),
                ConfigFile(dest="pi/agent/plannotator.json", content=_PLANNOTATOR_JSON),
                ConfigFile(dest="pi/launcher/pi.sh", content=_PI_LAUNCHER_SH, mode=0o755),
                ConfigFile(dest="pi/sandbox/pi-sandbox.sh", content=_PI_SANDBOX_SH, mode=0o755),
                ConfigFile(dest="pi/sandbox/pi-macos.sb", content=_PI_MACOS_SB),
            ),
            vendors=(
                VendorDir(
                    source=_agent_config_root() / "pi" / "agent",
                    dest="pi/agent",
                    include_globs=(
                        "AGENTS.md",
                        "APPEND_SYSTEM.md",
                        "agents/claude-pipeline/*.md",
                        "chains/pipeline.chain.md",
                        "prompts/pipeline.md",
                        "skills/pipeline/**",
                    ),
                ),
                VendorDir(
                    source=_pi_angelini_root(),
                    dest="pi-angelini",
                    exclude_dirs=GIT_ARTIFACTS | NODE_ARTIFACTS | PY_ARTIFACTS | frozenset({".pi-lens", ".pi-subagents", ".serena", "dist"}),
                    exclude_globs=("package-lock.json", "pi-system-audit-plan.md", "*.test.ts"),
                ),
            ),
            secrets=frozenset({"CONTEXT7_API_KEY", "EXA_API_KEY", "GCP_PROJECT_ID"}),
        )
