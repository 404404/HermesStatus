"""Shared HermesStatus device_v2 mode, configuration, and secret loading."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from multi_device_contracts import (
    ALLOWED_FIELDS,
    ENV_TO_FIELD,
    ClientContractError,
    ClientV2Config,
    parse_config_json,
    resolve_client_config,
    validate_readonly_file_path,
)


CONFIG_FILE_ENV = "HERMESSTATUS_CONFIG_FILE"
KNOWN_V2_ENV = set(ENV_TO_FIELD) | {CONFIG_FILE_ENV}
LEGACY_TRANSPORT_KEYS = {"SERVER", "PORT", "SERVERSTATUS_USER", "PASSWORD"}
MAX_CONFIG_FILE_BYTES = 64 << 10
MAX_CA_FILE_BYTES = 1 << 20
DEVICE_TOKEN_BYTES = 43
MAX_TOKEN_FILE_BYTES = DEVICE_TOKEN_BYTES + 2
DEVICE_TOKEN_RE = re.compile(rb"^[A-Za-z0-9_-]{43}$")


class ClientMode(Enum):
    LEGACY = "legacy"
    DEVICE_V2 = "device_v2"


@dataclass(frozen=True)
class ClientSelection:
    mode: ClientMode
    device_v2: ClientV2Config | None = None


def load_client_selection(
    arguments: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    loopback_test_profile: bool = False,
) -> ClientSelection:
    environment = dict(os.environ if environ is None else environ)
    cli_v2, cli_legacy = _parse_cli(arguments)
    environment_v2_keys = {
        key for key in environment if key.startswith("HERMESSTATUS_")
    }
    has_v2_signal = bool(cli_v2 or environment_v2_keys)
    if not has_v2_signal:
        return ClientSelection(mode=ClientMode.LEGACY)

    unknown_environment = environment_v2_keys - KNOWN_V2_ENV
    if unknown_environment:
        raise ClientContractError("environment contains unknown v2 fields")
    if any(environment[key] == "" for key in environment_v2_keys):
        raise ClientContractError("environment contains empty v2 fields")
    mixed_environment = {
        key for key in LEGACY_TRANSPORT_KEYS if key in environment
    }
    if cli_legacy or mixed_environment:
        raise ClientContractError("legacy and device_v2 configuration must not be mixed")

    config_file_value = cli_v2.pop(
        CONFIG_FILE_ENV,
        environment.get(CONFIG_FILE_ENV),
    )
    file_values: dict[str, Any] = {}
    if config_file_value not in (None, ""):
        config_path = validate_readonly_file_path(
            str(config_file_value),
            "config_file",
        )
        file_values = parse_config_json(
            _read_regular_file(
                config_path,
                maximum=MAX_CONFIG_FILE_BYTES,
                error_code="config file is unavailable",
            )
        )

    cli_values = {
        ENV_TO_FIELD[key]: value
        for key, value in cli_v2.items()
        if key in ENV_TO_FIELD
    }
    return ClientSelection(
        mode=ClientMode.DEVICE_V2,
        device_v2=resolve_client_config(
            cli=cli_values,
            env=environment,
            file_values=file_values,
            loopback_test_profile=loopback_test_profile,
        ),
    )


def load_device_token(path: str) -> str:
    validated_path = validate_readonly_file_path(path, "token_file")
    descriptor = _open_regular_file(
        validated_path,
        error_code="device token file is unavailable",
    )
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid():
            raise ClientContractError("device token file ownership is invalid")
        if stat.S_IMODE(metadata.st_mode) not in (0o400, 0o600):
            raise ClientContractError("device token file mode is invalid")
        if metadata.st_size not in (
            DEVICE_TOKEN_BYTES,
            DEVICE_TOKEN_BYTES + 1,
            DEVICE_TOKEN_BYTES + 2,
        ):
            raise ClientContractError("device token file size is invalid")
        data = _read_descriptor(descriptor, MAX_TOKEN_FILE_BYTES)
    finally:
        os.close(descriptor)
    if data.endswith(b"\r\n"):
        data = data[:-2]
    elif data.endswith(b"\n"):
        data = data[:-1]
    if len(data) != DEVICE_TOKEN_BYTES or DEVICE_TOKEN_RE.fullmatch(data) is None:
        raise ClientContractError("device token value is invalid")
    try:
        return data.decode("ascii")
    except UnicodeDecodeError:
        raise ClientContractError("device token value is invalid") from None


def load_custom_ca(path: str | None) -> str | None:
    if path is None:
        return None
    validated_path = validate_readonly_file_path(path, "ca_file")
    data = _read_regular_file(
        validated_path,
        maximum=MAX_CA_FILE_BYTES,
        error_code="custom CA file is unavailable",
    )
    if not data or b"\x00" in data:
        raise ClientContractError("custom CA file is invalid")
    try:
        return data.decode("ascii")
    except UnicodeDecodeError:
        raise ClientContractError("custom CA file is invalid") from None


def _parse_cli(arguments: Sequence[str]) -> tuple[dict[str, str], set[str]]:
    v2: dict[str, str] = {}
    legacy: set[str] = set()
    for argument in arguments:
        key, separator, value = argument.partition("=")
        if not separator:
            if key.startswith("HERMESSTATUS_"):
                raise ClientContractError("v2 CLI argument is invalid")
            continue
        if key.startswith("HERMESSTATUS_"):
            if key not in KNOWN_V2_ENV:
                raise ClientContractError("CLI contains unknown v2 fields")
            if value == "":
                raise ClientContractError("CLI contains empty v2 fields")
            if key in v2:
                raise ClientContractError("CLI contains duplicate v2 fields")
            v2[key] = value
        elif key in LEGACY_TRANSPORT_KEYS or key == "USER":
            legacy.add(key)
    return v2, legacy


def _open_regular_file(path: str, *, error_code: str) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise ClientContractError(error_code) from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ClientContractError(error_code)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _read_regular_file(path: str, *, maximum: int, error_code: str) -> bytes:
    descriptor = _open_regular_file(path, error_code=error_code)
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_size < 0 or metadata.st_size > maximum:
            raise ClientContractError(error_code)
        return _read_descriptor(descriptor, maximum)
    finally:
        os.close(descriptor)


def _read_descriptor(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(65536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > maximum:
        raise ClientContractError("secure file exceeds size limit")
    return data
