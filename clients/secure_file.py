"""Linux fail-closed, dirfd-relative reads for security-sensitive files."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from typing import Callable


class SecureFileError(RuntimeError):
    """A fixed, path-free secure file failure."""


@dataclass(frozen=True)
class _SecureOpenHooks:
    after_directory_open: Callable[[int, str, int], None] | None = None
    before_file_open: Callable[[int], None] | None = None
    after_file_open: Callable[[int], None] | None = None


def secure_open_regular_file(
    path: str,
    *,
    _test_hooks: _SecureOpenHooks | None = None,
) -> int:
    components = _validated_components(path)
    directory_flags, file_flags = _required_open_flags()
    current_descriptor = -1
    file_descriptor = -1
    try:
        current_descriptor = os.open("/", directory_flags)
        for depth, component in enumerate(components[:-1]):
            next_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=current_descriptor,
            )
            os.close(current_descriptor)
            current_descriptor = next_descriptor
            if (
                _test_hooks is not None
                and _test_hooks.after_directory_open is not None
            ):
                _test_hooks.after_directory_open(
                    depth,
                    component,
                    current_descriptor,
                )
        if _test_hooks is not None and _test_hooks.before_file_open is not None:
            _test_hooks.before_file_open(current_descriptor)
        file_descriptor = os.open(
            components[-1],
            file_flags,
            dir_fd=current_descriptor,
        )
        if _test_hooks is not None and _test_hooks.after_file_open is not None:
            _test_hooks.after_file_open(file_descriptor)
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SecureFileError("secure file is unavailable")
        result = file_descriptor
        file_descriptor = -1
        return result
    except (OSError, SecureFileError):
        raise SecureFileError("secure file is unavailable") from None
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if current_descriptor >= 0:
            os.close(current_descriptor)


def secure_read_bounded_regular_file(
    path: str,
    maximum: int,
    *,
    _test_hooks: _SecureOpenHooks | None = None,
) -> bytes:
    if not isinstance(maximum, int) or maximum < 0:
        raise SecureFileError("secure file is unavailable")
    descriptor = secure_open_regular_file(path, _test_hooks=_test_hooks)
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_size < 0 or metadata.st_size > maximum:
            raise SecureFileError("secure file is unavailable")
        return secure_read_bounded_descriptor(descriptor, maximum)
    finally:
        os.close(descriptor)


def secure_read_bounded_descriptor(descriptor: int, maximum: int) -> bytes:
    if not isinstance(maximum, int) or maximum < 0:
        raise SecureFileError("secure file is unavailable")
    chunks: list[bytes] = []
    remaining = maximum + 1
    try:
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError:
        raise SecureFileError("secure file is unavailable") from None
    data = b"".join(chunks)
    if len(data) > maximum:
        raise SecureFileError("secure file exceeds size limit")
    return data


def _validated_components(path: str) -> tuple[str, ...]:
    if (
        not isinstance(path, str)
        or not path
        or "\x00" in path
        or not path.startswith("/")
        or path.startswith("//")
        or os.path.normpath(path) != path
        or path == "/"
    ):
        raise SecureFileError("secure file path is invalid")
    components = tuple(path[1:].split("/"))
    if not components or any(
        component in ("", ".", "..") for component in components
    ):
        raise SecureFileError("secure file path is invalid")
    return components


def _required_open_flags() -> tuple[int, int]:
    required = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required):
        raise SecureFileError("secure file opening is unavailable")
    directory_flags = (
        os.O_RDONLY
        | os.O_CLOEXEC
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
    )
    file_flags = (
        os.O_RDONLY
        | os.O_CLOEXEC
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
    )
    return directory_flags, file_flags
