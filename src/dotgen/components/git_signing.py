from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment

_SETUP = r"""ensure_dir "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
if [ ! -f "$HOME/.ssh/id_signing" ]; then
  ssh-keygen -t ed25519 -a 100 -N "" \
    -C "$(detect_os)-$(hostname)-signing" \
    -f "$HOME/.ssh/id_signing"
fi
if bin_exists gh && gh auth status >/dev/null 2>&1; then
  _sig_key="$(awk '{print $2}' "$HOME/.ssh/id_signing.pub")"
  if ! gh ssh-key list 2>/dev/null | grep -qF "$_sig_key"; then
    gh ssh-key add "$HOME/.ssh/id_signing.pub" \
      --type signing \
      --title "$(detect_os)-$(hostname)-signing"
  fi
  unset _sig_key
else
  log "gh not authed; after 'gh auth login' run: gh ssh-key add ~/.ssh/id_signing.pub --type signing"
fi
"""


@dataclass(frozen=True)
class GitSigning:
    name: str = "git_signing"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        return Fragment(setup=_SETUP)
