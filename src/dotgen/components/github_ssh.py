from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_SETUP_COMMON = r"""ensure_dir "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

if [ ! -f "$HOME/.ssh/id_ed25519" ]; then
  ssh-keygen -t ed25519 -a 100 -N "" \
    -C "$(detect_os)-$(hostname)" \
    -f "$HOME/.ssh/id_ed25519"
fi

touch "$HOME/.ssh/known_hosts"
chmod 644 "$HOME/.ssh/known_hosts"
if ! grep -q '^github.com ' "$HOME/.ssh/known_hosts"; then
  ssh-keyscan -t rsa,ed25519 github.com >> "$HOME/.ssh/known_hosts" 2>/dev/null
fi
"""

_SETUP_MACOS_AGENT = r"""if ! pgrep -u "$USER" ssh-agent >/dev/null; then
  eval "$(ssh-agent -s)" >/dev/null
fi
ssh-add --apple-use-keychain "$HOME/.ssh/id_ed25519" 2>/dev/null || true
"""

_SETUP_TAIL = r"""log "Add this public key to GitHub: https://github.com/settings/keys"
cat "$HOME/.ssh/id_ed25519.pub" >&2
"""


@dataclass(frozen=True)
class GitHubSsh:
    name: str = "github_ssh"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        body = _SETUP_COMMON
        if env.os is OS.MACOS:
            body += _SETUP_MACOS_AGENT
        body += _SETUP_TAIL
        return Fragment(setup=body)
