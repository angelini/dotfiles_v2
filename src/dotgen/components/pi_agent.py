from dataclasses import dataclass

from dotgen.environment import Environment
from dotgen.fragment import Fragment


@dataclass(frozen=True)
class PiAgent:
    name: str = "pi_agent"

    def applies_to(self, env: Environment) -> bool:
        return True

    def render(self, env: Environment) -> Fragment:
        setup = 'install_npm_global @earendil-works/pi-coding-agent\ninstall_npm_global @dreki-gg/pi-context7\nensure_dir "$HOME/.pi"\nlink_file "$HOME/repos/lpi/AGENTS.md" "$HOME/.pi/AGENTS.md"\n'
        return Fragment(
            setup=setup,
            secrets=frozenset({"EXA_API_KEY", "CONTEXT7_API_KEY"}),
        )
