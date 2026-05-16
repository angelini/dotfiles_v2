from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment
from dotgen.types import OS

_BASHRC = r"""HISTSIZE=1000000
HISTFILESIZE=1000000
HISTCONTROL=ignoredups:erasedups
shopt -s histappend
ulimit -n 65536

set_win_title() {
  printf '\033]0;%s@%s:%s\007' "${USER:-?}" "${HOSTNAME%%.*}" "${PWD/#$HOME/~}"
}
PROMPT_COMMAND="set_win_title;${PROMPT_COMMAND:-}"

epoch() {
  python3 - "$1" <<'PYEOF'
import sys, datetime as d
print(d.datetime.fromtimestamp(int(sys.argv[1])).isoformat())
PYEOF
}
"""

_GL_PRETTY = '"%Cred%h%Creset -%C(yellow)%d%Creset %s %Cgreen(%cr) %C(bold blue)<%an>%Creset"'
_GL_ALIAS = f"alias gl='git log --color --graph --pretty=format:{_GL_PRETTY} --abbrev-commit'\n"

_ALIASES_COMMON = (
    r"""alias klear='clear && printf "\033[3J"'
alias rgc='rg -C 30'
alias ip='curl -s ifconfig.me'

# git
alias gs='git status'
alias ga='git add'
alias gc='git commit'
alias gpo='git push origin'
alias gpfo='git push --force-with-lease origin'
"""
    + _GL_ALIAS
)

_ALIAS_LS_MACOS = "alias l='ls -hlAG'\n"
_ALIAS_LS_LINUX = "alias l='ls -hlA --color=auto'\n"


_BASH_MACOS_SETUP = r"""if [ "$(detect_os)" = macos ]; then
  install_package bash
  if ! grep -q "/opt/homebrew/bin/bash" /etc/shells; then
    log "adding homebrew bash to /etc/shells"
    echo "/opt/homebrew/bin/bash" | sudo tee -a /etc/shells >/dev/null
  fi
  if [ "$SHELL" != "/opt/homebrew/bin/bash" ]; then
    log "changing shell to homebrew bash"
    sudo chsh -s /opt/homebrew/bin/bash "$(whoami)"
  fi
fi
"""


@dataclass(frozen=True)
class BashBase:
    name: str = "bash_base"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        ls_alias = _ALIAS_LS_MACOS if env.os is OS.MACOS else _ALIAS_LS_LINUX
        setup = _BASH_MACOS_SETUP if env.os is OS.MACOS else ""
        return Fragment(
            setup=setup,
            bashrc=_BASHRC,
            alias=_ALIASES_COMMON + ls_alias,
        )
