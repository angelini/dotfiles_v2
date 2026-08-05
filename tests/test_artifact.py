import hashlib
import io
import os
import stat
import subprocess
import tarfile
from pathlib import Path
from typing import cast

import pytest

from dotgen import artifact as artifact_module
from dotgen.artifact import ArtifactBuildError, FakeArtifactBuilder, ProductionArtifactBuilder
from dotgen.fragment import Fragment, GeneratedBinary
from dotgen.registry import ENVIRONMENTS
from dotgen.render import build_all


def _archive(*, unsafe_name: str | None = None, link: bool = False, missing_name: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in (
            ("stinkpot/go.mod", b"module example.test/stinkpot\n"),
            ("stinkpot/go.sum", b""),
            ("stinkpot/main.go", b"package main\nfunc main() {}\n"),
        ):
            if name.endswith(f"/{missing_name}"):
                continue
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        if unsafe_name is not None:
            info = tarfile.TarInfo(unsafe_name)
            content = b"unsafe"
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        if link:
            info = tarfile.TarInfo("stinkpot/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "main.go"
            archive.addfile(info)
    return buffer.getvalue()


def _declaration(archive: bytes, *, goos: str = "linux", goarch: str = "amd64", dest: str | None = None) -> GeneratedBinary:
    target = f"{goos}-{goarch}"
    return GeneratedBinary(
        name="stinkpot",
        dest=dest or f"artifacts/stinkpot/{target}/stinkpot",
        source_url="https://example.test/stinkpot.tar.gz",
        source_sha256=hashlib.sha256(archive).hexdigest(),
        go_version="1.26.4",
        goos=goos,
        goarch=goarch,
    )


def _runner(commands: list[tuple[list[str], dict[str, str]]]):
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = cast(dict[str, str], kwargs["env"])
        commands.append((command, env))
        if command == ["go", "version"]:
            return subprocess.CompletedProcess(command, 0, "go version go1.26.4 test/host\n", "")
        output = Path(command[command.index("-o") + 1])
        output.write_bytes(f"binary:{env['GOOS']}/{env['GOARCH']}".encode())
        return subprocess.CompletedProcess(command, 0, "", "")

    return run


def test_generated_binary_duplicate_destinations_fail_merge() -> None:
    archive = _archive()
    artifact = _declaration(archive)
    with pytest.raises(ValueError, match="duplicate artifact destination"):
        Fragment(artifacts=(artifact,)).merge(Fragment(artifacts=(artifact,)))


def test_build_all_fake_builder_builds_unique_targets_and_packages_exact_matrix(tmp_path: Path) -> None:
    builder = FakeArtifactBuilder()
    build_all(tmp_path, artifact_builder=builder)

    assert builder.builds == [
        ("stinkpot", "linux", "amd64"),
        ("stinkpot", "linux", "arm64"),
        ("stinkpot", "darwin", "arm64"),
    ]
    expected = {
        "debian": {"linux-amd64", "linux-arm64"},
        "debian-docker": {"linux-amd64", "linux-arm64"},
        "macos": {"darwin-arm64"},
    }
    for env_name in ENVIRONMENTS:
        target_root = tmp_path / env_name / "artifacts/stinkpot"
        targets = {path.parent.name for path in target_root.glob("*/stinkpot")}
        assert targets == expected[env_name]
        assert (target_root / "SHA256SUMS").is_file()
    assert not list(tmp_path.rglob("*darwin-amd64*"))


def test_production_builder_downloads_once_builds_targets_and_writes_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = _archive()
    downloads: list[str] = []
    commands: list[tuple[list[str], dict[str, str]]] = []

    def download(url: str) -> bytes:
        downloads.append(url)
        return archive

    monkeypatch.setenv("GOFLAGS", "-overlay=/tmp/untrusted")
    monkeypatch.setenv("GOWORK", "/tmp/untrusted.work")
    monkeypatch.setenv("GOAMD64", "v4")
    monkeypatch.setenv("GOEXPERIMENT", "untrusted")
    artifacts = (
        _declaration(archive),
        _declaration(archive, goarch="arm64"),
    )
    with ProductionArtifactBuilder(downloader=download, runner=_runner(commands)) as builder:
        builder.materialize(artifacts, tmp_path)
        second = tmp_path / "second"
        second.mkdir()
        builder.materialize(artifacts, second)

    assert downloads == ["https://example.test/stinkpot.tar.gz"]
    build_commands = [(command, env) for command, env in commands if command[:2] == ["go", "build"]]
    assert len(build_commands) == 2
    assert {(env["GOOS"], env["GOARCH"], env["CGO_ENABLED"]) for _, env in build_commands} == {
        ("linux", "amd64", "0"),
        ("linux", "arm64", "0"),
    }
    for command, env in build_commands:
        assert "-trimpath" in command
        assert "-buildvcs=false" in command
        assert "-ldflags=-s -w" in command
        assert env["GOTOOLCHAIN"] == "go1.26.4+auto"
        assert env["GOENV"] == "off"
        assert env["GOWORK"] == "off"
        assert env["GOFLAGS"] == ""
        assert env["GOEXPERIMENT"] == ""
        assert "GOAMD64" not in env
        assert not Path(env["GOMODCACHE"]).is_relative_to(tmp_path)
        assert not Path(env["GOCACHE"]).is_relative_to(tmp_path)

    manifest = (tmp_path / "artifacts/stinkpot/SHA256SUMS").read_text().splitlines()
    assert manifest == sorted(set(manifest))
    assert len(manifest) == 2
    for artifact in artifacts:
        output = tmp_path / artifact.dest
        assert stat.S_IMODE(output.stat().st_mode) == 0o755
        relative = Path(artifact.dest).relative_to("artifacts/stinkpot").as_posix()
        assert f"{hashlib.sha256(output.read_bytes()).hexdigest()}  {relative}" in manifest
    assert not list((tmp_path / "artifacts").rglob("go.mod"))
    assert not list((tmp_path / "artifacts").rglob("go.sum"))


@pytest.mark.parametrize("unsafe_name", ["../escape", "/absolute"])
def test_production_builder_rejects_unsafe_archive_members(tmp_path: Path, unsafe_name: str) -> None:
    archive = _archive(unsafe_name=unsafe_name)
    with ProductionArtifactBuilder(downloader=lambda _url: archive, runner=_runner([])) as builder, pytest.raises(ArtifactBuildError, match="unsafe archive member"):
        builder.materialize((_declaration(archive),), tmp_path)
    assert not (tmp_path / "artifacts").exists()


def test_production_builder_rejects_archive_links(tmp_path: Path) -> None:
    archive = _archive(link=True)
    with ProductionArtifactBuilder(downloader=lambda _url: archive, runner=_runner([])) as builder, pytest.raises(ArtifactBuildError, match="unsupported archive member type"):
        builder.materialize((_declaration(archive),), tmp_path)
    assert not (tmp_path / "artifacts").exists()


def test_production_builder_fails_closed_on_source_checksum(tmp_path: Path) -> None:
    archive = _archive()
    artifact = _declaration(archive)
    downloads = 0
    delays: list[float] = []

    def changed_download(_url: str) -> bytes:
        nonlocal downloads
        downloads += 1
        return archive + b"changed"

    with ProductionArtifactBuilder(downloader=changed_download, runner=_runner([]), sleeper=delays.append) as builder, pytest.raises(ArtifactBuildError, match="source checksum mismatch"):
        builder.materialize((artifact,), tmp_path)
    assert downloads == 1
    assert delays == []
    assert not (tmp_path / "artifacts").exists()


def test_production_builder_retries_until_source_checksum_matches(tmp_path: Path) -> None:
    archive = _archive()
    responses: list[bytes | Exception] = [OSError("transient"), b"error code: 520\n", archive]
    delays: list[float] = []

    def download(_url: str) -> bytes:
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    with ProductionArtifactBuilder(downloader=download, runner=_runner([]), sleeper=delays.append) as builder:
        builder.materialize((_declaration(archive),), tmp_path)

    assert responses == []
    assert delays == [0.25, 0.5]
    assert (tmp_path / "artifacts/stinkpot/linux-amd64/stinkpot").is_file()


def test_production_builder_reports_final_mixed_retry_failure(tmp_path: Path) -> None:
    archive = _archive()
    responses: list[bytes | Exception] = [b"error code: 520\n", OSError("offline-1"), OSError("offline-2"), OSError("offline-3"), OSError("offline-4")]

    def download(_url: str) -> bytes:
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    with ProductionArtifactBuilder(downloader=download, runner=_runner([]), sleeper=lambda _delay: None) as builder, pytest.raises(ArtifactBuildError, match="failed to download.*offline-4"):
        builder.materialize((_declaration(archive),), tmp_path)
    assert responses == []
    assert not (tmp_path / "artifacts").exists()


def test_production_builder_rejects_wrong_effective_go_version(tmp_path: Path) -> None:
    archive = _archive()

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "go version go1.25.5 test/host\n", "")

    with ProductionArtifactBuilder(downloader=lambda _url: archive, runner=runner) as builder, pytest.raises(ArtifactBuildError, match="requires effective Go 1.26.4"):
        builder.materialize((_declaration(archive),), tmp_path)
    assert not (tmp_path / "artifacts").exists()


def test_production_builder_reports_download_and_corrupt_archive_failures(tmp_path: Path) -> None:
    archive = _archive()

    def failed_download(_url: str) -> bytes:
        raise OSError("offline")

    with ProductionArtifactBuilder(downloader=failed_download, runner=_runner([]), sleeper=lambda _delay: None) as builder, pytest.raises(ArtifactBuildError, match="failed to download"):
        builder.materialize((_declaration(archive),), tmp_path)

    corrupt = b"not a tar archive"
    with ProductionArtifactBuilder(downloader=lambda _url: corrupt, runner=_runner([])) as builder, pytest.raises(ArtifactBuildError, match="invalid source archive"):
        builder.materialize((_declaration(corrupt),), tmp_path)
    assert not (tmp_path / "artifacts").exists()


def test_production_builder_rejects_missing_required_source_file(tmp_path: Path) -> None:
    archive = _archive(missing_name="main.go")
    with ProductionArtifactBuilder(downloader=lambda _url: archive, runner=_runner([])) as builder, pytest.raises(ArtifactBuildError, match="required source file is not regular"):
        builder.materialize((_declaration(archive),), tmp_path)
    assert not (tmp_path / "artifacts").exists()


def test_compile_failure_preserves_existing_artifacts(tmp_path: Path) -> None:
    archive = _archive()
    artifact = _declaration(archive)
    FakeArtifactBuilder().materialize((artifact,), tmp_path)
    existing = tmp_path / artifact.dest
    existing.write_bytes(b"previous working artifact")

    def failed_build(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if command == ["go", "version"]:
            return subprocess.CompletedProcess(command, 0, "go version go1.26.4 test/host\n", "")
        raise subprocess.CalledProcessError(1, command, stderr="compile failed")

    with ProductionArtifactBuilder(downloader=lambda _url: archive, runner=failed_build) as builder, pytest.raises(ArtifactBuildError, match="compile failed"):
        builder.materialize((artifact,), tmp_path)
    assert existing.read_bytes() == b"previous working artifact"


def test_interrupted_publication_restores_previous_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = _archive()
    artifact = _declaration(archive)
    FakeArtifactBuilder().materialize((artifact,), tmp_path)
    existing = tmp_path / artifact.dest
    existing.write_bytes(b"previous working artifact")
    real_replace = os.replace

    def interrupted_replace(source: Path, destination: Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        if source_path.name == "artifacts" and destination_path == tmp_path / "artifacts" and (tmp_path / ".artifacts.backup").exists():
            raise KeyboardInterrupt
        real_replace(source, destination)

    monkeypatch.setattr(artifact_module.os, "replace", interrupted_replace)
    with pytest.raises(KeyboardInterrupt):
        FakeArtifactBuilder().materialize((artifact,), tmp_path)

    assert existing.read_bytes() == b"previous working artifact"
    assert not (tmp_path / ".artifacts.backup").exists()
