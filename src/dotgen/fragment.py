from dataclasses import dataclass

from dotgen.vendor import VendorDir


@dataclass(frozen=True)
class ConfigFile:
    dest: str
    content: str
    mode: int = 0o644


@dataclass(frozen=True)
class GeneratedBinary:
    name: str
    dest: str
    source_url: str
    source_sha256: str
    go_version: str
    goos: str
    goarch: str
    source_subdir: str = "."
    build_flags: tuple[str, ...] = ("-trimpath", "-buildvcs=false")
    ldflags: tuple[str, ...] = ("-s", "-w")
    mode: int = 0o755


@dataclass(frozen=True)
class Fragment:
    setup: str = ""
    alias: str = ""
    bashrc: str = ""
    configs: tuple[ConfigFile, ...] = ()
    vendors: tuple[VendorDir, ...] = ()
    artifacts: tuple[GeneratedBinary, ...] = ()
    secrets: frozenset[str] = frozenset()

    def merge(self, other: "Fragment") -> "Fragment":
        artifacts = self.artifacts + other.artifacts
        destinations = [artifact.dest for artifact in artifacts]
        if len(destinations) != len(set(destinations)):
            duplicate = next(dest for index, dest in enumerate(destinations) if dest in destinations[:index])
            raise ValueError(f"duplicate artifact destination: {duplicate}")
        return Fragment(
            setup=_join(self.setup, other.setup),
            alias=_join(self.alias, other.alias),
            bashrc=_join(self.bashrc, other.bashrc),
            configs=self.configs + other.configs,
            vendors=self.vendors + other.vendors,
            artifacts=artifacts,
            secrets=self.secrets | other.secrets,
        )


def _join(a: str, b: str) -> str:
    if not a:
        return b
    if not b:
        return a
    left = a.rstrip("\n")
    return f"{left}\n\n{b}"
