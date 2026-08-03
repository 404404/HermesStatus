#!/usr/bin/env python3
"""Copy a validated stats snapshot into a new data directory without overwrite."""

import argparse
import hashlib
import json
import os
import pathlib
import re
import stat
import sys
import tempfile

CLIENT_DIRECTORY = pathlib.Path(__file__).resolve().parents[1] / "clients"
if str(CLIENT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIRECTORY))

from secure_file import (  # noqa: E402
    SecureFileError,
    secure_open_regular_file,
    secure_read_bounded_descriptor,
)


SECRET_KEY = re.compile(
    r"(?i)^(authorization|api[_-]?key|password|secret|token[_-]?secret|access[_-]?token|refresh[_-]?token|cookie)$"
)
MAX_SOURCE_BYTES = 64 << 20


class MigrationError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 3):
        super().__init__(message)
        self.exit_code = exit_code


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_fingerprint(info: os.stat_result) -> tuple:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def reject_symlink_components(path: pathlib.Path, label: str) -> None:
    candidate = path.absolute()
    while True:
        try:
            mode = os.lstat(candidate).st_mode
        except FileNotFoundError:
            parent = candidate.parent
            if parent == candidate:
                return
            candidate = parent
            continue
        if stat.S_ISLNK(mode):
            raise MigrationError("%s path contains a symbolic link" % label, 3)
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and copy stats.json into a new bind-mount directory."
    )
    parser.add_argument("--source", required=True, help="existing stats.json")
    parser.add_argument("--target-directory", required=True, help="new data directory")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the copy; without this flag the command is a dry-run",
    )
    return parser.parse_args()


def validate_document(value, path="$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET_KEY.search(str(key)):
                raise MigrationError("secret-like field name rejected at %s" % path)
            validate_document(child, path + "." + str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_document(child, "%s[%d]" % (path, index))


def read_source(source: pathlib.Path) -> tuple[bytes, tuple, str]:
    try:
        descriptor = secure_open_regular_file(str(source.absolute()))
    except SecureFileError:
        raise MigrationError("source must be a regular file", 3)
    try:
        before = os.fstat(descriptor)
        data = secure_read_bounded_descriptor(descriptor, MAX_SOURCE_BYTES)
        after = os.fstat(descriptor)
    except (OSError, SecureFileError) as exc:
        raise MigrationError("source could not be read", 3) from exc
    finally:
        os.close(descriptor)
    fingerprint = file_fingerprint(before)
    if fingerprint != file_fingerprint(after):
        raise MigrationError("source changed while it was being read", 3)
    try:
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError("source is not valid JSON", 3) from exc
    if not isinstance(document, dict) or not isinstance(document.get("servers"), list):
        raise MigrationError("source must be a stats object with a servers array", 3)
    validate_document(document)
    return data, fingerprint, digest(data)


def verify_source_unchanged(
    source: pathlib.Path, expected_fingerprint: tuple, expected_digest: str
) -> None:
    try:
        descriptor = secure_open_regular_file(str(source.absolute()))
    except SecureFileError as exc:
        raise MigrationError("source could not be rechecked", 3) from exc
    try:
        before = os.fstat(descriptor)
        data = secure_read_bounded_descriptor(descriptor, MAX_SOURCE_BYTES)
        after = os.fstat(descriptor)
    except (OSError, SecureFileError) as exc:
        raise MigrationError("source could not be rechecked", 3) from exc
    finally:
        os.close(descriptor)
    if (
        file_fingerprint(before) != expected_fingerprint
        or file_fingerprint(after) != expected_fingerprint
        or digest(data) != expected_digest
    ):
        raise MigrationError("source changed during migration", 3)


def validate_target_directory(target_directory: pathlib.Path) -> None:
    reject_symlink_components(target_directory, "target")
    if not target_directory.exists():
        return
    if not target_directory.is_dir():
        raise MigrationError("target directory must be a directory", 4)
    target = target_directory / "stats.json"
    if target.exists() or target.is_symlink():
        raise MigrationError("target stats.json already exists; refusing to overwrite", 4)
    try:
        next(target_directory.iterdir())
    except StopIteration:
        return
    raise MigrationError("target directory must be empty", 4)


def write_and_sync(descriptor: int, data: bytes) -> None:
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def migrate(source: pathlib.Path, target_directory: pathlib.Path, apply: bool) -> dict:
    data, source_fingerprint, source_digest = read_source(source)
    validate_target_directory(target_directory)
    target = target_directory / "stats.json"
    result = {
        "mode": "apply" if apply else "dry-run",
        "bytes": len(data),
        "sha256": source_digest,
        "source": "validated stats input",
        "target": target.name,
    }
    if not apply:
        return result

    target_directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    validate_target_directory(target_directory)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".stats-migration-", suffix=".tmp", dir=str(target_directory)
    )
    temporary = pathlib.Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        write_descriptor = descriptor
        descriptor = -1
        write_and_sync(write_descriptor, data)
        if digest(temporary.read_bytes()) != source_digest:
            raise MigrationError("temporary file checksum mismatch", 3)
        verify_source_unchanged(source, source_fingerprint, source_digest)
        try:
            os.link(str(temporary), str(target))
        except FileExistsError as exc:
            raise MigrationError("target stats.json already exists; refusing to overwrite", 4) from exc
        directory_fd = os.open(str(target_directory), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return result


def main() -> int:
    args = parse_args()
    try:
        result = migrate(
            pathlib.Path(args.source), pathlib.Path(args.target_directory), args.apply
        )
    except MigrationError as exc:
        print("stats migration failed: %s" % exc, file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print("stats migration failed: filesystem operation failed", file=sys.stderr)
        return 5
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
