from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_SETUP_MACOS = "install_cask google-cloud-sdk\n"
_GCLOUD_VERSION = "587.0.0"
_GCLOUD_RELEASE_BASE = "https://dl.google.com/dl/cloudsdk/release/downloads/for_packagers/linux"
_GCLOUD_SHA256 = {
    "amd64": "6b566621ce59a900d520a30d505b9cef1c2bdd72826103175727ac6db1702101",
    "arm64": "c7808b357c1781ed1f0fa0876316ebb901aa86727fb17e2ede229de8b94d95b0",
}

_SETUP_DEBIAN = """add_repo apt google-cloud-sdk \\
  "deb [signed-by=/etc/apt/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \\
  "https://packages.cloud.google.com/apt/doc/apt-key.gpg"
update_pkg_index
install_package google-cloud-cli
"""

_SETUP_CACHYOS = f'''\
_install_gcloud_cachyos() (
  local asset_arch checksum root marker parent archive="" stage="" extracted actual
  case "$(detect_arch)" in
    x86_64) asset_arch=amd64; checksum={_GCLOUD_SHA256["amd64"]} ;;
    aarch64|arm64) asset_arch=aarch64; checksum={_GCLOUD_SHA256["arm64"]} ;;
    *) error "unsupported arch for Google Cloud CLI: $(detect_arch)"; exit 1 ;;
  esac
  root="$HOME/.local/share/google-cloud-sdk"
  marker="$root/.dotgen-archive-sha256"
  parent="${{root%/*}}"
  if [ -e "$root" ] || [ -L "$root" ]; then
    if [ ! -d "$root" ] || [ -L "$root" ]; then
      error "unsafe Google Cloud CLI destination: $root"
      exit 1
    fi
  fi
  if [ -f "$marker" ] && [ ! -L "$marker" ] && [ "$(cat "$marker")" = "$checksum" ] && \
    bin_version_matches "$root/bin/gcloud" "{_GCLOUD_VERSION}" version; then
    exit 0
  fi
  ensure_dir "$parent"
  archive="$(mktemp)"
  stage="$(mktemp -d "$parent/.google-cloud-sdk.XXXXXX")"
  trap 'rm -f -- "$archive"; [ -z "$stage" ] || rm -rf -- "$stage"' EXIT
  curl -fsSL \
    "{_GCLOUD_RELEASE_BASE}/google-cloud-cli_{_GCLOUD_VERSION}.orig_${{asset_arch}}.tar.gz" \
    -o "$archive"
  actual="$(sha256_file "$archive")"
  if [ "$actual" != "$checksum" ]; then
    error "Google Cloud CLI archive checksum mismatch"
    exit 1
  fi
  tar -xzf "$archive" -C "$stage"
  extracted="$stage/google-cloud-sdk"
  if ! bin_version_matches "$extracted/bin/gcloud" "{_GCLOUD_VERSION}" version; then
    error "Google Cloud CLI archive version mismatch"
    exit 1
  fi
  printf '%s\n' "$checksum" > "$extracted/.dotgen-archive-sha256"
  chmod 0644 "$extracted/.dotgen-archive-sha256"
  rm -rf -- "$root"
  mv -- "$extracted" "$root"
)
_install_gcloud_cachyos
remove_packages google-cloud-cli
'''

_SETUP_BY_OS: dict[OS, str] = {
    OS.CACHYOS: _SETUP_CACHYOS,
    OS.MACOS: _SETUP_MACOS,
    OS.DEBIAN: _SETUP_DEBIAN,
}

_BASHRC_BY_OS: dict[OS, str] = {
    OS.CACHYOS: """\
for _f in \\
  "$HOME/.local/share/google-cloud-sdk/path.bash.inc" \\
  "$HOME/.local/share/google-cloud-sdk/completion.bash.inc"; do
  [ -f "$_f" ] && source "$_f"
done
unset _f
""",
    OS.DEBIAN: """\
for _f in \\
  "/opt/homebrew/share/google-cloud-sdk/path.bash.inc" \\
  "/opt/homebrew/share/google-cloud-sdk/completion.bash.inc" \\
  "/usr/lib/google-cloud-sdk/path.bash.inc" \\
  "/usr/lib/google-cloud-sdk/completion.bash.inc"; do
  [ -f "$_f" ] && source "$_f"
done
unset _f
""",
    OS.MACOS: """\
for _f in \\
  "/opt/homebrew/share/google-cloud-sdk/path.bash.inc" \\
  "/opt/homebrew/share/google-cloud-sdk/completion.bash.inc" \\
  "/usr/lib/google-cloud-sdk/path.bash.inc" \\
  "/usr/lib/google-cloud-sdk/completion.bash.inc"; do
  [ -f "$_f" ] && source "$_f"
done
unset _f
""",
}

_ALIASES = r"""alias gcp='gcloud config configurations activate default'

get_project_roles() {
  local account="${1}"
  local project
  project="$(gcloud config get project)"
  gcloud projects get-iam-policy "${project}" \
    --flatten="bindings[].members" \
    --format="table(bindings.role)" \
    --filter="bindings.members:${account}"
}

get_sa_bindings() {
  local account="${1}"
  gcloud iam service-accounts get-iam-policy "${account}" \
    --flatten="bindings[].members" \
    --format="table(bindings.role, bindings.members)"
}
"""


@dataclass(frozen=True)
class Gcloud:
    name: str = "gcloud"

    def applies_to(self, env: Environment) -> bool:
        return env.os in _SETUP_BY_OS

    def render(self, env: Environment) -> Fragment:
        return Fragment(
            setup=_SETUP_BY_OS[env.os],
            bashrc=_BASHRC_BY_OS[env.os],
            alias=_ALIASES,
        )
