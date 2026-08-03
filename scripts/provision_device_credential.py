#!/usr/bin/env python3
"""Provision one HermesStatus device credential without network access."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

CLIENT_DIRECTORY = Path(__file__).resolve().parents[1] / "clients"
if str(CLIENT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIRECTORY))

from secure_file import (  # noqa: E402
    SecureFileError,
    secure_open_regular_file,
    secure_read_bounded_descriptor,
)


DEVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
TOKEN_BYTES = 32
TOKEN_LENGTH = 43
MAX_CREDENTIAL_BYTES = 64 << 10
SLOT_IDS = {"current", "next"}


class ProvisionError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Target:
    path: Path
    exists: bool


@dataclass(frozen=True)
class ProvisionArguments:
    device_id: str
    client_token_file: str
    server_credential_file: str
    slot: str
    not_before: str
    not_after: str
    overwrite: bool
    dry_run: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create an offline HermesStatus device token and digest record.",
    )
    parser.add_argument("device_id")
    parser.add_argument("--client-token-file", required=True)
    parser.add_argument("--server-credential-file", required=True)
    parser.add_argument("--slot", choices=sorted(SLOT_IDS), default="current")
    parser.add_argument("--not-before", required=True)
    parser.add_argument("--not-after", required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def provision(
    arguments: ProvisionArguments,
    *,
    stdout,
    token_factory: Callable[[int], bytes] = secrets.token_bytes,
) -> None:
    if DEVICE_ID_RE.fullmatch(arguments.device_id) is None:
        raise ProvisionError("invalid_device_id")
    not_before = _parse_utc(arguments.not_before)
    not_after = _parse_utc(arguments.not_after)
    if not_after <= not_before:
        raise ProvisionError("invalid_credential_window")

    client_target = _validate_target(
        arguments.client_token_file,
        overwrite=arguments.overwrite,
    )
    server_target = _validate_target(
        arguments.server_credential_file,
        overwrite=arguments.overwrite,
    )
    if client_target.path == server_target.path:
        raise ProvisionError("targets_must_differ")

    existing_record = None
    if server_target.exists:
        existing_record = _load_existing_record(
            server_target.path,
            arguments.device_id,
        )

    if arguments.dry_run:
        print("validation success", file=stdout)
        print(f"device_id: {arguments.device_id}", file=stdout)
        return

    token_bytes = token_factory(TOKEN_BYTES)
    if not isinstance(token_bytes, bytes) or len(token_bytes) != TOKEN_BYTES:
        raise ProvisionError("random_source_failed")
    token = base64.urlsafe_b64encode(token_bytes).rstrip(b"=")
    if len(token) != TOKEN_LENGTH:
        raise ProvisionError("random_source_failed")
    digest = hashlib.sha256(token).hexdigest()
    slot = {
        "id": arguments.slot,
        "digest": digest,
        "not_before": arguments.not_before,
        "not_after": arguments.not_after,
    }
    record = _merge_record(existing_record, arguments.device_id, slot)
    credential_bytes = (
        json.dumps(record, indent=2, sort_keys=False).encode("utf-8") + b"\n"
    )
    _write_pair_atomically(
        (
            (server_target, credential_bytes),
            (client_target, token + b"\n"),
        ),
        overwrite=arguments.overwrite,
    )
    print(f"device_id: {arguments.device_id}", file=stdout)
    print(f"client token file: {client_target.path}", file=stdout)
    print(f"server credential file: {server_target.path}", file=stdout)


def _validate_target(raw_path: str, *, overwrite: bool) -> Target:
    if "\x00" in raw_path:
        raise ProvisionError("invalid_target")
    path = Path(raw_path)
    if not path.is_absolute() or Path(os.path.normpath(raw_path)) != path:
        raise ProvisionError("invalid_target")
    parent = path.parent
    try:
        parent_info = parent.lstat()
    except OSError:
        raise ProvisionError("invalid_target") from None
    if not stat.S_ISDIR(parent_info.st_mode) or parent.resolve() != parent:
        raise ProvisionError("invalid_target")
    if not os.access(parent, os.W_OK | os.X_OK):
        raise ProvisionError("target_not_writable")
    try:
        target_info = path.lstat()
    except FileNotFoundError:
        return Target(path=path, exists=False)
    except OSError:
        raise ProvisionError("invalid_target") from None
    if not stat.S_ISREG(target_info.st_mode):
        raise ProvisionError("invalid_target")
    if not overwrite:
        raise ProvisionError("target_exists")
    return Target(path=path, exists=True)


def _parse_utc(value: str) -> dt.datetime:
    if RFC3339_UTC_RE.fullmatch(value) is None:
        raise ProvisionError("invalid_credential_window")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ProvisionError("invalid_credential_window") from None
    if parsed.tzinfo != dt.timezone.utc:
        raise ProvisionError("invalid_credential_window")
    return parsed


def _load_existing_record(path: Path, device_id: str) -> dict:
    descriptor = _open_regular(path)
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_size < 1 or metadata.st_size > MAX_CREDENTIAL_BYTES:
            raise ProvisionError("invalid_existing_credential")
        data = _read_descriptor(descriptor, MAX_CREDENTIAL_BYTES)
    finally:
        os.close(descriptor)
    try:
        record = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProvisionError("invalid_existing_credential") from None
    if not isinstance(record, dict) or set(record) != {
        "version",
        "device_id",
        "algorithm",
        "credentials",
    }:
        raise ProvisionError("invalid_existing_credential")
    if (
        record["version"] != 1
        or record["device_id"] != device_id
        or record["algorithm"] != "sha256"
        or not isinstance(record["credentials"], list)
        or not 1 <= len(record["credentials"]) <= 2
    ):
        raise ProvisionError("invalid_existing_credential")
    seen_slots: set[str] = set()
    seen_digests: set[str] = set()
    for credential in record["credentials"]:
        if not isinstance(credential, dict) or set(credential) != {
            "id",
            "digest",
            "not_before",
            "not_after",
        }:
            raise ProvisionError("invalid_existing_credential")
        slot_id = credential["id"]
        digest = credential["digest"]
        if (
            slot_id not in SLOT_IDS
            or slot_id in seen_slots
            or not isinstance(digest, str)
            or DIGEST_RE.fullmatch(digest) is None
            or digest in seen_digests
        ):
            raise ProvisionError("invalid_existing_credential")
        if _parse_utc_for_existing(credential["not_after"]) <= _parse_utc_for_existing(
            credential["not_before"]
        ):
            raise ProvisionError("invalid_existing_credential")
        seen_slots.add(slot_id)
        seen_digests.add(digest)
    return record


def _parse_utc_for_existing(value) -> dt.datetime:
    if not isinstance(value, str):
        raise ProvisionError("invalid_existing_credential")
    try:
        return _parse_utc(value)
    except ProvisionError:
        raise ProvisionError("invalid_existing_credential") from None


def _merge_record(existing: dict | None, device_id: str, slot: dict) -> dict:
    credentials = []
    if existing is not None:
        credentials.extend(
            credential
            for credential in existing["credentials"]
            if credential["id"] != slot["id"]
        )
    credentials.append(slot)
    credentials.sort(key=lambda credential: credential["id"] != "current")
    return {
        "version": 1,
        "device_id": device_id,
        "algorithm": "sha256",
        "credentials": credentials,
    }


def _open_regular(path: Path) -> int:
    try:
        return secure_open_regular_file(str(path))
    except SecureFileError:
        raise ProvisionError("invalid_existing_credential") from None


def _read_descriptor(descriptor: int, maximum: int) -> bytes:
    try:
        return secure_read_bounded_descriptor(descriptor, maximum)
    except SecureFileError:
        raise ProvisionError("invalid_existing_credential")


def _write_pair_atomically(
    files: Sequence[tuple[Target, bytes]],
    *,
    overwrite: bool,
) -> None:
    staged: list[tuple[Target, Path]] = []
    committed: list[Target] = []
    try:
        for target, data in files:
            staged.append((target, _stage_file(target.path, data)))
        for target, temporary in staged:
            if overwrite and target.exists:
                os.replace(temporary, target.path)
            else:
                os.link(temporary, target.path, follow_symlinks=False)
                temporary.unlink()
            committed.append(target)
            _sync_directory(target.path.parent)
    except OSError:
        for target in reversed(committed):
            if not target.exists:
                try:
                    target.path.unlink()
                    _sync_directory(target.path.parent)
                except OSError:
                    pass
        raise ProvisionError("atomic_write_failed") from None
    finally:
        for _target, temporary in staged:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _stage_file(path: Path, data: bytes) -> Path:
    descriptor = -1
    temporary_path = ""
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".hermesstatus-credential-",
            dir=path.parent,
        )
        os.fchmod(descriptor, 0o600)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(descriptor)
    except OSError:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        raise ProvisionError("atomic_write_failed") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return Path(temporary_path)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main(argv: Sequence[str] | None = None) -> int:
    namespace = build_parser().parse_args(argv)
    arguments = ProvisionArguments(
        device_id=namespace.device_id,
        client_token_file=namespace.client_token_file,
        server_credential_file=namespace.server_credential_file,
        slot=namespace.slot,
        not_before=namespace.not_before,
        not_after=namespace.not_after,
        overwrite=namespace.overwrite,
        dry_run=namespace.dry_run,
    )
    try:
        provision(arguments, stdout=os.sys.stdout)
    except ProvisionError as error:
        print(f"provision failed code={error.code}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
