import shlex


def quote(s: str) -> str:
    return shlex.quote(s)


def argv(*parts: str) -> str:
    return " ".join(shlex.quote(p) for p in parts)


def heredoc(tag: str, body: str) -> str:
    chosen = tag
    suffix = 0
    while _tag_collides(chosen, body):
        suffix += 1
        chosen = f"{tag}_{suffix}"
    trailing = "" if body.endswith("\n") else "\n"
    return f"<<'{chosen}'\n{body}{trailing}{chosen}\n"


def guard_if_bin(name: str, body: str) -> str:
    return f"if ! command -v {shlex.quote(name)} >/dev/null 2>&1; then\n{_indent(body)}\nfi\n"


def _tag_collides(tag: str, body: str) -> bool:
    return any(line.strip() == tag for line in body.splitlines())


def _indent(body: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line if line else line for line in body.splitlines())
