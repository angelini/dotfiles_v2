from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from types import FrameType
from typing import Protocol

from dotgen.fragment import GeneratedBinary


class ArtifactBuildError(RuntimeError):
    pass


class ArtifactBuilder(Protocol):
    def materialize(self, artifacts: tuple[GeneratedBinary, ...], out_dir: Path) -> None: ...


Runner = Callable[..., subprocess.CompletedProcess[str]]
Downloader = Callable[[str], bytes]
Sleeper = Callable[[float], None]

_SOURCE_DOWNLOAD_ATTEMPTS = 5
_SOURCE_RETRY_BASE_SECONDS = 0.25
_TRANSIENT_SOURCE_BODIES = frozenset({b"error code: 520\n"})


class ProductionArtifactBuilder:
    def __init__(self, *, downloader: Downloader | None = None, runner: Runner = subprocess.run, sleeper: Sleeper = time.sleep) -> None:
        self._downloader = downloader or _download
        self._runner = runner
        self._sleeper = sleeper
        self._sources: dict[tuple[str, str], bytes] = {}
        self._builds: dict[tuple[object, ...], bytes] = {}
        self._verified_go_versions: set[str] = set()
        self._work = tempfile.TemporaryDirectory(prefix="dotgen-artifacts-")
        self._work_root = Path(self._work.name)

    def close(self) -> None:
        self._work.cleanup()

    def __enter__(self) -> ProductionArtifactBuilder:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def materialize(self, artifacts: tuple[GeneratedBinary, ...], out_dir: Path) -> None:
        if not artifacts:
            return
        with _handled_build_signals():
            outputs = {artifact.dest: self._build(artifact) for artifact in artifacts}
            _publish(artifacts, outputs, out_dir)

    def _build(self, artifact: GeneratedBinary) -> bytes:
        _validate_declaration(artifact)
        key = (
            artifact.source_url,
            artifact.source_sha256,
            artifact.go_version,
            artifact.goos,
            artifact.goarch,
            artifact.source_subdir,
            artifact.build_flags,
            artifact.ldflags,
        )
        cached = self._builds.get(key)
        if cached is not None:
            return cached

        archive = self._source(artifact)
        self._verify_go(artifact.go_version)
        build_root = Path(tempfile.mkdtemp(prefix=f"{artifact.name}-{artifact.goos}-{artifact.goarch}-", dir=self._work_root))
        try:
            source_root = _extract(archive, build_root / "source")
            source_dir = source_root / artifact.source_subdir
            _require_regular_files(source_dir, ("go.mod", "go.sum", "main.go"))
            output = build_root / "output"
            env = _go_environment(artifact.go_version)
            env.update(
                {
                    "CGO_ENABLED": "0",
                    "GOOS": artifact.goos,
                    "GOARCH": artifact.goarch,
                }
            )
            command = [
                "go",
                "build",
                *artifact.build_flags,
                f"-ldflags={' '.join(artifact.ldflags)}",
                "-o",
                str(output),
                ".",
            ]
            self._run(command, cwd=source_dir, env=env, operation=f"build {artifact.goos}/{artifact.goarch}")
            if not _is_regular_file(output):
                raise ArtifactBuildError(f"Go build did not produce a regular file: {output}")
            built = output.read_bytes()
            self._builds[key] = built
            return built
        finally:
            shutil.rmtree(build_root, ignore_errors=True)

    def _source(self, artifact: GeneratedBinary) -> bytes:
        key = (artifact.source_url, artifact.source_sha256)
        cached = self._sources.get(key)
        if cached is not None:
            return cached

        last_error: Exception | None = None
        last_actual: str | None = None
        for attempt in range(_SOURCE_DOWNLOAD_ATTEMPTS):
            try:
                archive = self._downloader(artifact.source_url)
            except Exception as error:
                last_error = error
                last_actual = None
            else:
                actual = hashlib.sha256(archive).hexdigest()
                if actual == artifact.source_sha256:
                    self._sources[key] = archive
                    return archive
                if archive not in _TRANSIENT_SOURCE_BODIES:
                    raise ArtifactBuildError(f"source checksum mismatch for {artifact.source_url}: expected {artifact.source_sha256}, got {actual}")
                last_error = None
                last_actual = actual
            if attempt + 1 < _SOURCE_DOWNLOAD_ATTEMPTS:
                self._sleeper(_SOURCE_RETRY_BASE_SECONDS * 2**attempt)

        if last_actual is not None:
            raise ArtifactBuildError(f"source checksum mismatch for {artifact.source_url} after {_SOURCE_DOWNLOAD_ATTEMPTS} attempts: expected {artifact.source_sha256}, got {last_actual}")
        raise ArtifactBuildError(f"failed to download {artifact.source_url} after {_SOURCE_DOWNLOAD_ATTEMPTS} attempts: {last_error}") from last_error

    def _verify_go(self, version: str) -> None:
        if version in self._verified_go_versions:
            return
        env = _go_environment(version)
        result = self._run(["go", "version"], cwd=self._work_root, env=env, operation=f"select Go {version}")
        match = re.search(r"\bgo version go([^\s]+)", result.stdout)
        effective = match.group(1) if match else "unknown"
        if effective != version:
            raise ArtifactBuildError(f"generated artifact requires effective Go {version}, got {effective}; install a Go launcher that supports GOTOOLCHAIN=go{version}+auto")
        self._verified_go_versions.add(version)

    def _run(self, command: list[str], *, cwd: Path, env: dict[str, str], operation: str) -> subprocess.CompletedProcess[str]:
        try:
            return self._runner(command, cwd=cwd, env=env, check=True, capture_output=True, text=True)
        except FileNotFoundError as error:
            raise ArtifactBuildError(f"failed to {operation}: Go launcher not found") from error
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or str(error)).strip()
            raise ArtifactBuildError(f"failed to {operation}: {detail}") from error
        except subprocess.SubprocessError as error:
            raise ArtifactBuildError(f"failed to {operation}: {error}") from error


class FakeArtifactBuilder:
    def __init__(self) -> None:
        self.builds: list[tuple[str, str, str]] = []
        self._outputs: dict[tuple[str, str, str], bytes] = {}

    def materialize(self, artifacts: tuple[GeneratedBinary, ...], out_dir: Path) -> None:
        outputs: dict[str, bytes] = {}
        for artifact in artifacts:
            _validate_declaration(artifact)
            key = (artifact.name, artifact.goos, artifact.goarch)
            if key not in self._outputs:
                self.builds.append(key)
                self._outputs[key] = f"dotgen fake artifact: {artifact.name} {artifact.goos}/{artifact.goarch}\n".encode()
            outputs[artifact.dest] = self._outputs[key]
        if artifacts:
            _publish(artifacts, outputs, out_dir)


def _go_environment(version: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GO")}
    env.update(
        {
            "GOENV": "off",
            "GOEXPERIMENT": "",
            "GOFLAGS": "",
            "GOTOOLCHAIN": f"go{version}+auto",
            "GOWORK": "off",
        }
    )
    return env


@contextmanager
def _handled_build_signals() -> Generator[None]:
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    watched = tuple(sig for sig in (getattr(signal, "SIGHUP", None), signal.SIGTERM) if sig is not None)
    previous = {sig: signal.getsignal(sig) for sig in watched}

    def interrupt(signum: int, _frame: FrameType | None) -> None:
        raise ArtifactBuildError(f"artifact build interrupted by signal {signum}")

    try:
        for sig in watched:
            signal.signal(sig, interrupt)
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "dotgen-artifact-builder/1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _validate_declaration(artifact: GeneratedBinary) -> None:
    if not artifact.source_url.startswith("https://"):
        raise ArtifactBuildError(f"artifact source must use HTTPS: {artifact.source_url}")
    if not re.fullmatch(r"[0-9a-f]{64}", artifact.source_sha256):
        raise ArtifactBuildError(f"invalid source SHA-256 for {artifact.name}")
    if artifact.mode != 0o755:
        raise ArtifactBuildError(f"generated executable mode must be 0755: {artifact.dest}")
    path = PurePosixPath(artifact.dest)
    if path.is_absolute() or ".." in path.parts or path.parts[:2] != ("artifacts", artifact.name) or len(path.parts) < 4:
        raise ArtifactBuildError(f"invalid artifact destination: {artifact.dest}")
    subdir = PurePosixPath(artifact.source_subdir)
    if subdir.is_absolute() or ".." in subdir.parts:
        raise ArtifactBuildError(f"invalid artifact source subdirectory: {artifact.source_subdir}")


def _extract(archive: bytes, dest: Path) -> Path:
    dest.mkdir(parents=True)
    archive_path = dest.parent / "source.tar.gz"
    archive_path.write_bytes(archive)
    try:
        with tarfile.open(archive_path, mode="r:gz") as tar:
            members = tar.getmembers()
            _validate_members(members)
            tar.extractall(dest, members=members, filter="data")
    except (OSError, tarfile.TarError, ValueError) as error:
        raise ArtifactBuildError(f"invalid source archive: {error}") from error
    finally:
        archive_path.unlink(missing_ok=True)

    entries = list(dest.iterdir())
    if len(entries) != 1 or not entries[0].is_dir() or entries[0].is_symlink():
        raise ArtifactBuildError("source archive must contain exactly one top-level directory")
    return entries[0]


def _validate_members(members: Iterable[tarfile.TarInfo]) -> None:
    seen: set[PurePosixPath] = set()
    for member in members:
        path = PurePosixPath(member.name)
        if not member.name or path.is_absolute() or ".." in path.parts:
            raise ArtifactBuildError(f"unsafe archive member: {member.name!r}")
        if path in seen:
            raise ArtifactBuildError(f"duplicate archive member: {member.name}")
        seen.add(path)
        if not (member.isdir() or member.isreg()):
            raise ArtifactBuildError(f"unsupported archive member type: {member.name}")


def _require_regular_files(directory: Path, names: tuple[str, ...]) -> None:
    if not directory.is_dir() or directory.is_symlink():
        raise ArtifactBuildError(f"source subdirectory is not a regular directory: {directory}")
    for name in names:
        path = directory / name
        if not _is_regular_file(path):
            raise ArtifactBuildError(f"required source file is not regular: {path}")


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def _publish(artifacts: tuple[GeneratedBinary, ...], outputs: dict[str, bytes], out_dir: Path) -> None:
    if len(outputs) != len(artifacts):
        raise ArtifactBuildError("duplicate artifact output destination")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    stage_parent = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}-artifacts-", dir=out_dir.parent))
    stage_artifacts = stage_parent / "artifacts"
    try:
        grouped: dict[str, list[GeneratedBinary]] = {}
        for artifact in artifacts:
            grouped.setdefault(artifact.name, []).append(artifact)
            destination = stage_parent / artifact.dest
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(outputs[artifact.dest])
            destination.chmod(artifact.mode)

        for name, declarations in grouped.items():
            manifest_root = stage_artifacts / name
            lines: list[str] = []
            for artifact in declarations:
                relative = PurePosixPath(artifact.dest).relative_to(PurePosixPath("artifacts") / name)
                digest = hashlib.sha256(outputs[artifact.dest]).hexdigest()
                lines.append(f"{digest}  {relative.as_posix()}\n")
            if len(lines) != len(set(lines)):
                raise ArtifactBuildError(f"duplicate checksum entry for artifact {name}")
            (manifest_root / "SHA256SUMS").write_text("".join(sorted(lines)))

        final = out_dir / "artifacts"
        backup = out_dir / ".artifacts.backup"
        if _path_exists(backup):
            if _path_exists(final):
                _remove_path(backup)
            else:
                os.replace(backup, final)

        moved_existing = False
        published = False
        try:
            if _path_exists(final):
                os.replace(final, backup)
                moved_existing = True
            os.replace(stage_artifacts, final)
            published = True
        except KeyboardInterrupt:
            _restore_artifact_backup(final, backup, moved_existing, published)
            raise
        except Exception:
            _restore_artifact_backup(final, backup, moved_existing, published)
            raise
        if _path_exists(backup):
            _remove_path(backup)
    finally:
        shutil.rmtree(stage_parent, ignore_errors=True)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _restore_artifact_backup(final: Path, backup: Path, moved_existing: bool, published: bool) -> None:
    if moved_existing and not published and not _path_exists(final) and _path_exists(backup):
        os.replace(backup, final)


def _remove_path(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError as error:
        raise ArtifactBuildError(f"failed to remove stale artifact path {path}: {error}") from error
