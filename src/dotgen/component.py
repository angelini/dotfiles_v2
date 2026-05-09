from typing import TYPE_CHECKING, Protocol

from dotgen.fragment import Fragment

if TYPE_CHECKING:
    from dotgen.environment import Environment


class Component(Protocol):
    @property
    def name(self) -> str: ...

    def applies_to(self, env: "Environment") -> bool: ...

    def render(self, env: "Environment") -> Fragment: ...
