import subprocess

import pytest

from dotgen.bash import argv, guard_if_bin, heredoc, quote


@pytest.mark.parametrize("s", ["foo", "with space", "$dollar", "single'quote", "", "a;b|c&d"])
def test_quote_round_trips_through_bash(s: str) -> None:
    quoted = quote(s)
    out = subprocess.check_output(["bash", "-c", f"printf %s {quoted}"]).decode()
    assert out == s


def test_argv_joins_quoted_parts() -> None:
    line = argv("git", "commit", "-m", "hello world")
    out = subprocess.check_output(["bash", "-c", f"for a in {line}; do printf '%s|' \"$a\"; done"])
    assert out.decode() == "git|commit|-m|hello world|"


def test_heredoc_basic_tag() -> None:
    out = heredoc("EOF", "line1\nline2\n")
    assert out.startswith("<<'EOF'\n")
    assert out.rstrip().endswith("EOF")


def test_heredoc_avoids_collision_with_body() -> None:
    body = "before\nEOF\nafter\n"
    out = heredoc("EOF", body)
    assert "<<'EOF_1'" in out
    assert out.rstrip().endswith("EOF_1")


def test_guard_if_bin_uses_command_v() -> None:
    out = guard_if_bin("jq", "echo install jq")
    assert "command -v jq" in out
    assert "echo install jq" in out
    assert out.startswith("if ! ")
    assert out.rstrip().endswith("fi")
