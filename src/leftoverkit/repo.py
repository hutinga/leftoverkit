"""Git and filesystem operations for one local project."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any

GIT_ENV = {key: val for key, val in os.environ.items() if not key.startswith("GIT_")} | {
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_TERMINAL_PROMPT": "0",
}
INTEGRATION = {"dev", "develop", "main", "master", "prod", "qa", "release", "staging"}


class SafetyError(Exception):
    """An operation cannot safely continue."""


def git(directory: Path, *args: str, allow_no_match: bool = False) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(directory),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.quotePath=false",
            "-c",
            "protocol.allow=never",
            *(("--literal-pathspecs",) if args[0] != "check-ignore" else ()),
            *args,
        ],
        check=False,
        env=GIT_ENV,
        capture_output=True,
        encoding="utf-8",
        errors="surrogateescape",
        timeout=90,
    )
    if result.returncode and not (allow_no_match and result.returncode == 1):
        message = result.stderr.strip() or f"exit {result.returncode}"
        raise SafetyError(f"git {args[0]}: {message}")
    return result.stdout


class Repo:
    def __init__(self, directory: Path):
        self.root = Path(git(directory.resolve(), "rev-parse", "--show-toplevel").rstrip("\n")).resolve()
        self.common = Path(
            git(self.root, "rev-parse", "--path-format=absolute", "--git-common-dir").rstrip("\n")
        ).resolve()
        self.state = self.common / "leftoverkit"
        self.primary = Path(self.worktrees()[0]["worktree"]).resolve()
        if self.state.exists() or self.state.is_symlink():
            require_private(self.state)

    def worktrees(self) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for entry in git(self.root, "worktree", "list", "--porcelain", "-z").split("\0"):
            key, _, value = entry.partition(" ")
            if key == "worktree":
                entries.append({key: value})
            elif key:
                entries[-1][key] = value
        if not entries:
            raise SafetyError("Git did not return a primary worktree.")
        return entries

    def tracked(self, path: Path) -> bool:
        # Treat case and Unicode aliases conservatively on all filesystems.
        relative = normalize_path(path.relative_to(self.root).as_posix())
        for tracked in git(self.root, "ls-files", "--cached", "-z").split("\0"):
            alias = normalize_path(tracked)
            if alias == relative or alias.startswith(relative + "/"):
                return True
        return False

    def ignored(self, path: Path) -> bool:
        return bool(
            git(
                self.root,
                "check-ignore",
                "--",
                path.relative_to(self.root).as_posix(),
                allow_no_match=True,
            )
        )

    def integrated(self, head: str) -> bool:
        refs = git(
            self.root, "for-each-ref", f"--contains={head}", "--format=%(refname)", "refs/remotes"
        )
        return any(ref.split("/", 3)[-1] in INTEGRATION for ref in refs.splitlines())

    def input_path(self, value: str) -> Path:
        path = Path(os.path.abspath(self.root / value))
        temp_alias = Path("/tmp")
        if sys.platform == "darwin" and inside(path, temp_alias):
            path = temp_alias.resolve() / path.relative_to(temp_alias)
        if path.resolve() != path:
            raise SafetyError("The path or one of its parents is a symbolic link.")
        return path


def system_temp_roots() -> set[Path]:
    roots = {Path("/tmp").resolve()}
    if sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/bin/getconf", "DARWIN_USER_TEMP_DIR"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            root = Path(result.stdout.strip()).resolve()
            if root.name == "T" and inside(root, Path("/private/var/folders")):
                roots.add(root)
    return roots


def normalize_path(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def require_private(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SafetyError(f"Expected a private directory owned by this user: {path}")


def private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, exist_ok=True)
    require_private(path)
    return path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists() and not path.is_symlink():
        return default
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as stream:
        return json.load(stream)


def sync_directory(path: Path) -> None:
    with directory_fd(path) as fd:
        os.fsync(fd)


def write_json(path: Path, data: Any) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, encoding="utf-8", delete=False
    ) as stream:
        temp = Path(stream.name)
        try:
            json.dump(data, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temp, path)
            sync_directory(path.parent)
        finally:
            temp.unlink(missing_ok=True)


@contextlib.contextmanager
def directory_fd(path: Path) -> Iterator[int]:
    if not path.is_absolute():
        raise SafetyError("Expected an absolute path.")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def sensitive_name(name: str) -> bool:
    value = name.casefold()
    return value.startswith((".env", "credential", "id_rsa", "id_ed25519")) or value.endswith(
        (".pem", ".key", ".p12")
    )


def signature(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def inspect(path: Path) -> tuple[tuple[int, ...], str, int, float]:
    """Fingerprint names and metadata without opening file contents or following links."""
    root = path.lstat()
    digest = hashlib.sha256()
    size = 0
    modified = root.st_mtime

    def add(relative: Path, info: os.stat_result) -> None:
        nonlocal size, modified
        if info.st_uid != os.getuid() or info.st_dev != root.st_dev:
            raise SafetyError("Contains files from another user or filesystem.")
        if stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                raise SafetyError("Contains a hard-linked file.")
            size += info.st_size
        elif not stat.S_ISDIR(info.st_mode):
            raise SafetyError("Contains a symbolic link or a special file.")
        modified = max(modified, info.st_mtime)
        digest.update(os.fsencode(relative))
        digest.update(repr(signature(info)).encode())

    add(Path("."), root)
    if stat.S_ISDIR(root.st_mode):

        def traversal_error(error: OSError) -> None:
            raise error

        for directory, dirs, files in os.walk(path, onerror=traversal_error):
            dirs.sort()
            for name in sorted(dirs + files):
                child = Path(directory) / name
                if name.casefold() == ".git" or sensitive_name(name):
                    raise SafetyError("Contains a Git marker or a sensitive path.")
                add(child.relative_to(path), child.lstat())
    return signature(root), digest.hexdigest(), size, modified


def rename_checked(source: Path, target: Path, expected: tuple[int, ...]) -> None:
    with directory_fd(source.parent) as src, directory_fd(target.parent) as dst:
        current = os.stat(source.name, dir_fd=src, follow_symlinks=False)
        if signature(current) != expected:
            raise SafetyError("Item changed during cleanup.")
        try:
            os.stat(target.name, dir_fd=dst, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise SafetyError("Destination already exists.")
        # The destination is either private tool storage or an original path guarded
        # by an atomic no-replace rename. The syscall never follows a final symlink.
        rename_no_replace(src, source.name, dst, target.name)
        os.fsync(src)
        os.fsync(dst)


def rename_no_replace(src: int, source: str, dst: int, target: str) -> None:
    import ctypes
    import sys

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = getattr(libc, "renameatx_np", None)
        flag = 0x00000004  # RENAME_EXCL
    else:
        function = getattr(libc, "renameat2", None)
        flag = 1  # RENAME_NOREPLACE
    if function is None:
        raise SafetyError("This system does not support a no-overwrite rename.")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(src, os.fsencode(source), dst, os.fsencode(target), flag):
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), str(target))


def processes() -> set[Path]:
    executable = shutil.which("lsof") or ("/usr/sbin/lsof" if Path("/usr/sbin/lsof").is_file() else None)
    if executable is None:
        raise SafetyError("lsof is unavailable; automatic moves are disabled.")
    result = subprocess.run(
        [executable, "-w", "-a", "-u", str(os.getuid()), "-F0fn"],
        check=False,
        capture_output=True,
        timeout=25,
    )
    fields = (field.lstrip(b"\n") for field in result.stdout.split(b"\0"))
    paths = {Path(os.fsdecode(field[1:])).resolve() for field in fields if field.startswith(b"n/")}
    if result.returncode or not paths:
        raise SafetyError("Could not verify which files are in use; automatic moves are disabled.")
    return paths
