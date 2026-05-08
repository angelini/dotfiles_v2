from dataclasses import dataclass


@dataclass(frozen=True)
class ConfigFile:
    dest: str
    content: str
    mode: int = 0o644


@dataclass(frozen=True)
class Fragment:
    setup: str = ""
    alias: str = ""
    bashrc: str = ""
    configs: tuple[ConfigFile, ...] = ()

    def merge(self, other: "Fragment") -> "Fragment":
        return Fragment(
            setup=_join(self.setup, other.setup),
            alias=_join(self.alias, other.alias),
            bashrc=_join(self.bashrc, other.bashrc),
            configs=self.configs + other.configs,
        )


def _join(a: str, b: str) -> str:
    if not a:
        return b
    if not b:
        return a
    sep = "" if a.endswith("\n") else "\n"
    return f"{a}{sep}{b}"
