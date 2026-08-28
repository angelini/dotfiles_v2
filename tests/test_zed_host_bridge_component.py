import json
import os
import plistlib
import socket
import subprocess
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

from dotgen.components.zed_host_bridge import ZedHostBridge
from dotgen.registry import ENVIRONMENTS

BRIDGE = Path(__file__).resolve().parents[1] / "src/dotgen/resources/zed_host_bridge/bridge.mjs"


def _node() -> str:
    node = Path.home() / ".local/share/fnm/aliases/default/bin/node"
    if not node.is_file():
        pytest.skip("managed Node runtime is not installed")
    return str(node)


def test_component_distribution_ordering_and_deployment_input() -> None:
    for name in ("debian", "macos"):
        components = [component.name for component in ENVIRONMENTS[name].components]
        assert components.count("zed_host_bridge") == 1
        assert components.index("node_fnm") < components.index("zed_host_bridge")
        assert components.index("zed_host_bridge") < components.index("git_setup")
    macos = [component.name for component in ENVIRONMENTS["macos"].components]
    assert macos.index("zed") < macos.index("zed_host_bridge")
    assert "zed_host_bridge" not in [component.name for component in ENVIRONMENTS["debian-docker"].components]

    debian_fragment = ZedHostBridge().render(ENVIRONMENTS["debian"])
    macos_fragment = ZedHostBridge().render(ENVIRONMENTS["macos"])
    assert not debian_fragment.secrets
    assert macos_fragment.secrets == frozenset({"ZED_HOST_BRIDGE_SSH_HOST"})
    assert {config.dest for config in debian_fragment.configs} == {"zed-host-bridge/bridge.mjs", "zed-host-bridge/zed"}
    assert {config.dest for config in macos_fragment.configs} == {
        "zed-host-bridge/bridge.mjs",
        "zed-host-bridge/config.json.template",
        "zed-host-bridge/serve",
        "zed-host-bridge/dev.dotgen.zed-host-bridge.plist",
        "zed-host-bridge/ssh.conf.template",
    }


def test_launch_agent_and_ssh_resources_are_scoped() -> None:
    fragment = ZedHostBridge().render(ENVIRONMENTS["macos"])
    configs = {config.dest: config for config in fragment.configs}
    plist = plistlib.loads(configs["zed-host-bridge/dev.dotgen.zed-host-bridge.plist"].content.encode())
    assert plist["Label"] == "dev.dotgen.zed-host-bridge"
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True
    assert plist["ThrottleInterval"] == 10
    assert plist["EnvironmentVariables"]["PATH"] == "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
    command = plist["ProgramArguments"]
    assert command[:2] == ["/bin/bash", "-c"]
    assert command[2] == 'exec "$HOME/.local/libexec/dotgen/zed-host-bridge-serve"'

    ssh_config = configs["zed-host-bridge/ssh.conf.template"].content
    assert ssh_config.startswith("Host ${ZED_HOST_BRIDGE_SSH_HOST}\n")
    assert "RemoteForward /home/%r/.cache/dotgen/zed-host-bridge.sock %d/Library/Caches/dotgen/zed-host-bridge.sock" in ssh_config
    assert "StreamLocalBindMask 0177" in ssh_config
    assert "StreamLocalBindUnlink yes" in ssh_config
    assert "ExitOnForwardFailure yes" in ssh_config
    assert "Host *" not in ssh_config


def _run_client(home: Path, socket_path: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node(), str(BRIDGE), "client", *args],
        cwd=cwd,
        env={**os.environ, "HOME": str(home), "ZED_HOST_BRIDGE_SOCKET": str(socket_path)},
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _one_shot_receiver(socket_path: Path, captured: list[dict[str, object]]) -> threading.Thread:
    ready = threading.Event()

    def receive() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(socket_path))
            ready.set()
            server.listen(1)
            connection, _ = server.accept()
            with connection:
                payload = b""
                while not payload.endswith(b"\n"):
                    payload += connection.recv(65536)
                captured.append(json.loads(payload))
                connection.sendall(b'{"ok":true,"exitCode":0}\n')

    thread = threading.Thread(target=receive, daemon=True)
    thread.start()
    assert ready.wait(2)
    return thread


def test_client_round_trips_paths_positions_and_options(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "repos/project name"
    project.mkdir(parents=True)
    file_path = project / "unicode-λ.py"
    file_path.write_text("pass\n")
    socket_path = tmp_path / "bridge.sock"
    captured: list[dict[str, object]] = []
    receiver = _one_shot_receiver(socket_path, captured)

    result = _run_client(home, socket_path, project, "--new", "--wait", "unicode-λ.py:42:5", "new file.txt")

    receiver.join(2)
    assert result.returncode == 0, result.stderr
    assert captured == [
        {
            "version": 1,
            "behavior": "new",
            "wait": True,
            "paths": [
                {"relativePath": "project name/unicode-λ.py", "line": 42, "column": 5},
                {"relativePath": "project name/new file.txt"},
            ],
        }
    ]


def test_client_existing_filename_colon_wins_and_defaults_to_cwd(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "repos/project"
    project.mkdir(parents=True)
    (project / "name:12").write_text("data\n")
    socket_path = tmp_path / "bridge.sock"
    captured: list[dict[str, object]] = []
    receiver = _one_shot_receiver(socket_path, captured)
    result = _run_client(home, socket_path, project, "name:12")
    receiver.join(2)

    assert result.returncode == 0, result.stderr
    assert captured[0]["paths"] == [{"relativePath": "project/name:12"}]

    socket_path.unlink(missing_ok=True)
    captured.clear()
    receiver = _one_shot_receiver(socket_path, captured)
    result = _run_client(home, socket_path, project)
    receiver.join(2)
    assert result.returncode == 0, result.stderr
    assert captured[0]["paths"] == [{"relativePath": "project"}]


@pytest.mark.parametrize("args", [("--diff", "."), ("--bad", "."), ("-",), ("https://example.com",), ("--new", "--add", "."), ("file.txt:0",), ("file.txt:12:0",)])
def test_client_rejects_unsupported_arguments_without_connecting(tmp_path: Path, args: tuple[str, ...]) -> None:
    home = tmp_path / "home"
    project = home / "repos/project"
    project.mkdir(parents=True)
    result = _run_client(home, tmp_path / "missing.sock", project, *args)
    assert result.returncode != 0
    assert "unavailable" not in result.stderr


def test_client_rejects_traversal_and_symlink_escape(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "repos/project"
    outside = tmp_path / "outside"
    project.mkdir(parents=True)
    outside.mkdir()
    (project / "escape").symlink_to(outside, target_is_directory=True)
    for operand in ("../../../outside", "escape/file.txt"):
        result = _run_client(home, tmp_path / "missing.sock", project, operand)
        assert result.returncode != 0
        assert "outside $HOME/repos" in result.stderr


@contextmanager
def _server(tmp_path: Path, ssh_host: str = "debian-dev", exit_code: int = 0) -> Generator[tuple[Path, Path]]:
    socket_path = tmp_path / "server.sock"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"sshHost": ssh_host}))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    argv_log = tmp_path / "zed-argv"
    fake_zed = fake_bin / "zed"
    fake_zed.write_text('#!/usr/bin/env bash\nprintf \'%s\\0\' "$@" > "$ZED_ARGV_LOG"\nexit "${ZED_EXIT_CODE:-0}"\n')
    fake_zed.chmod(0o755)
    process = subprocess.Popen(
        [_node(), str(BRIDGE), "serve"],
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "ZED_ARGV_LOG": str(argv_log),
            "ZED_EXIT_CODE": str(exit_code),
            "ZED_HOST_BRIDGE_CONFIG": str(config),
            "ZED_HOST_BRIDGE_SOCKET": str(socket_path),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while process.poll() is None and time.monotonic() < deadline:
        if socket_path.exists() and socket_path.stat().st_mode & 0o777 == 0o600:
            break
        time.sleep(0.02)
    if not socket_path.exists():
        _, stderr = process.communicate(timeout=2)
        pytest.fail(f"bridge server failed to start: {stderr}")
    assert socket_path.stat().st_mode & 0o777 == 0o600
    try:
        yield socket_path, argv_log
    finally:
        process.terminate()
        process.wait(timeout=5)
        assert not socket_path.exists()


def _request(socket_path: Path, value: object) -> dict[str, object]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall(json.dumps(value).encode() + b"\n")
        client.shutdown(socket.SHUT_WR)
        payload = b""
        while not payload.endswith(b"\n"):
            payload += client.recv(65536)
    return json.loads(payload)


def test_receiver_propagates_zed_exit_status(tmp_path: Path) -> None:
    with _server(tmp_path, exit_code=23) as (socket_path, _):
        response = _request(
            socket_path,
            {"version": 1, "behavior": "default", "wait": False, "paths": [{"relativePath": "project/file.txt"}]},
        )
    assert response["ok"] is False
    assert response["exitCode"] == 23


def test_receiver_builds_fixed_remote_urls_and_exact_argv(tmp_path: Path) -> None:
    with _server(tmp_path) as (socket_path, argv_log):
        response = _request(
            socket_path,
            {
                "version": 1,
                "behavior": "reuse",
                "wait": True,
                "paths": [
                    {"relativePath": "project/a file#λ.py", "line": 12, "column": 3},
                    {"relativePath": "project/second.txt"},
                ],
            },
        )
    assert response == {"ok": True, "exitCode": 0}
    assert argv_log.read_bytes().split(b"\0")[:-1] == [
        b"--reuse",
        b"--wait",
        b"ssh://debian-dev/~/repos/project/a%20file%23%CE%BB.py:12:3",
        b"ssh://debian-dev/~/repos/project/second.txt",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 1, "behavior": "default", "wait": False, "paths": [{"relativePath": "../escape"}]},
        {"version": 1, "behavior": "default", "wait": False, "paths": [{"relativePath": "project//file"}]},
        {"version": 1, "behavior": "default", "wait": False, "paths": [{"relativePath": "https://bad"}]},
        {"version": 1, "behavior": "default", "wait": False, "paths": [{"relativePath": "project/file", "column": 2}]},
        {"version": 1, "behavior": "default", "wait": False, "paths": [], "extra": True},
    ],
)
def test_receiver_rejects_adversarial_requests_without_launching(tmp_path: Path, payload: dict[str, object]) -> None:
    with _server(tmp_path) as (socket_path, argv_log):
        response = _request(socket_path, payload)
        assert response["ok"] is False
        assert not argv_log.exists()


@pytest.mark.parametrize("alias", ["", "bad host", "*.example", "/host", "-option", "host_underscore", "host\ncontrol"])
def test_macos_setup_rejects_invalid_alias_before_writing(tmp_path: Path, alias: str) -> None:
    setup = ZedHostBridge().render(ENVIRONMENTS["macos"]).setup
    script = tmp_path / "setup.sh"
    script.write_text(f"set -euo pipefail\nload_secrets() {{ :; }}\nerror() {{ printf '%s\\n' \"$*\" >&2; }}\n{setup}")
    home = tmp_path / "home"
    result = subprocess.run(
        ["bash", str(script)],
        env={"HOME": str(home), "ZED_HOST_BRIDGE_SSH_HOST": alias, "PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "must be an exact SSH alias" in result.stderr
    assert not home.exists()


def test_macos_setup_installs_atomic_scoped_ssh_include_and_defers_headless_launchd(tmp_path: Path) -> None:
    fragment = ZedHostBridge().render(ENVIRONMENTS["macos"])
    bundle = tmp_path / "bundle"
    for config in fragment.configs:
        destination = bundle / "config" / config.dest
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(config.content)
        destination.chmod(config.mode)

    home = tmp_path / "home"
    managed_node = home / ".local/share/fnm/aliases/default/bin/node"
    managed_node.parent.mkdir(parents=True)
    managed_node.symlink_to(_node())
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    ssh_main = ssh_dir / "config"
    ssh_main.write_text("Host debian-dev\nInclude ~/.ssh/config.d/dotgen-zed-host-bridge.conf\n  HostName example.test")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "ssh").write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' 'exitonforwardfailure yes' 'streamlocalbindunlink yes' 'streamlocalbindmask 0177' "
        "'remoteforward /home/alex/.cache/dotgen/zed-host-bridge.sock /Users/alex/Library/Caches/dotgen/zed-host-bridge.sock'\n"
    )
    (fake_bin / "launchctl").write_text("#!/usr/bin/env bash\nexit 1\n")
    (fake_bin / "stat").write_text("#!/usr/bin/env bash\nid -u\n")
    for executable in fake_bin.iterdir():
        executable.chmod(0o755)

    script = tmp_path / "setup.sh"
    script.write_text(
        "set -euo pipefail\n"
        "load_secrets() { :; }\n"
        "error() { printf '%s\\n' \"$*\" >&2; }\n"
        "log() { printf '%s\\n' \"$*\"; }\n"
        'install_config_template() { local tmp; mkdir -p "$(dirname "$2")"; tmp=$(mktemp); '
        'sed "s|\\${ZED_HOST_BRIDGE_SSH_HOST}|$ZED_HOST_BRIDGE_SSH_HOST|g" "$1" > "$tmp"; install -m "${4:-0644}" "$tmp" "$2"; rm -f "$tmp"; }\n'
        f"DIR={bundle}\n"
        f"{fragment.setup}"
    )
    env = {
        "HOME": str(home),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "ZED_HOST_BRIDGE_SSH_HOST": "debian-dev",
    }
    for _ in range(2):
        result = subprocess.run(["bash", str(script)], env=env, check=False, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "activation deferred" in result.stdout

    assert ssh_main.read_text() == "Include ~/.ssh/config.d/dotgen-zed-host-bridge.conf\nHost debian-dev\n  HostName example.test"
    include = ssh_dir / "config.d/dotgen-zed-host-bridge.conf"
    assert include.stat().st_mode & 0o777 == 0o600
    assert include.read_text().startswith("Host debian-dev\n")
    receiver_config = json.loads((home / ".config/dotgen/zed-host-bridge.json").read_text())
    assert receiver_config == {"sshHost": "debian-dev"}
