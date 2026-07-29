"""Pure HermesStatus 2.2 Client contracts.

This Stage A module performs no network I/O, DNS, TLS, token-file reads, or
production entrypoint integration.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit


DEVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
MAX_ENVELOPE_BYTES = 1 << 20

ENV_TO_FIELD = {
    "HERMESSTATUS_SERVER_URL": "server_url",
    "HERMESSTATUS_DEVICE_ID": "device_id",
    "HERMESSTATUS_DEVICE_NAME": "device_name",
    "HERMESSTATUS_DEVICE_FQDN": "device_fqdn",
    "HERMESSTATUS_DEVICE_TOKEN_FILE": "token_file",
    "HERMESSTATUS_TLS_VERIFY": "verify_tls",
    "HERMESSTATUS_CONNECT_TIMEOUT_SECONDS": "connect_timeout_seconds",
    "HERMESSTATUS_READ_TIMEOUT_SECONDS": "read_timeout_seconds",
    "HERMESSTATUS_COLLECTION_INTERVAL_SECONDS": "collection_interval_seconds",
}
ALLOWED_FIELDS = {
    "server_url",
    "device_id",
    "device_name",
    "device_fqdn",
    "token_file",
    "verify_tls",
    "connect_timeout_seconds",
    "read_timeout_seconds",
    "collection_interval_seconds",
}
FORBIDDEN_AMBIGUOUS_KEYS = {"DOMAIN", "TOKEN", "PASSWORD", "AUTHORIZATION"}


class ClientContractError(ValueError):
    """A sanitized configuration or envelope contract failure."""


@dataclass(frozen=True)
class ClientV2Config:
    server_url: str
    device_id: str
    device_name: str | None
    device_fqdn: str | None
    token_file: str
    verify_tls: bool = True
    connect_timeout_seconds: int = 10
    read_timeout_seconds: int = 30
    collection_interval_seconds: int = 60
    loopback_test_profile: bool = False


class MockTransport(Protocol):
    def send(self, endpoint: str, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        """Record/return a synthetic response without real network I/O."""


class RecordingMockTransport:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = dict(response)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def send(self, endpoint: str, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((endpoint, dict(envelope)))
        return dict(self.response)


def parse_config_json(data: str | bytes) -> dict[str, Any]:
    try:
        document = json.loads(data)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ClientContractError("config is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ClientContractError("config root must be an object")
    _require_keys(document, {"version", "server", "device", "collection"}, "config")
    if document["version"] != 1:
        raise ClientContractError("config.version must equal 1")
    server = _object(document["server"], "server")
    device = _object(document["device"], "device")
    collection = _object(document["collection"], "collection")
    _require_keys(
        server,
        {"url", "verify_tls", "connect_timeout_seconds", "read_timeout_seconds"},
        "server",
    )
    _require_keys(device, {"id", "name", "fqdn", "token_file"}, "device")
    _require_keys(collection, {"interval_seconds"}, "collection")
    return {
        "server_url": server["url"],
        "verify_tls": server["verify_tls"],
        "connect_timeout_seconds": server["connect_timeout_seconds"],
        "read_timeout_seconds": server["read_timeout_seconds"],
        "device_id": device["id"],
        "device_name": device["name"],
        "device_fqdn": device["fqdn"],
        "token_file": device["token_file"],
        "collection_interval_seconds": collection["interval_seconds"],
    }


def resolve_client_config(
    *,
    cli: Mapping[str, Any] | None = None,
    env: Mapping[str, Any] | None = None,
    file_values: Mapping[str, Any] | None = None,
    loopback_test_profile: bool = False,
) -> ClientV2Config:
    cli = dict(cli or {})
    env = dict(env or {})
    file_values = dict(file_values or {})
    _reject_ambiguous(cli, "CLI")
    _reject_ambiguous(env, "environment")
    _reject_unknown(cli, ALLOWED_FIELDS, "CLI")
    _reject_unknown(file_values, ALLOWED_FIELDS, "file")

    env_values: dict[str, Any] = {}
    for env_key, field in ENV_TO_FIELD.items():
        if env_key in env and env[env_key] not in (None, ""):
            env_values[field] = env[env_key]

    merged: dict[str, Any] = {
        "verify_tls": True,
        "connect_timeout_seconds": 10,
        "read_timeout_seconds": 30,
        "collection_interval_seconds": 60,
        "device_name": None,
        "device_fqdn": None,
    }
    merged.update(file_values)
    merged.update(env_values)
    merged.update(cli)

    missing = [
        field
        for field in ("server_url", "device_id", "token_file")
        if merged.get(field) in (None, "")
    ]
    if missing:
        raise ClientContractError(
            "incomplete v2 configuration: missing " + ",".join(sorted(missing))
        )

    verify_tls = _bool_value(merged["verify_tls"], "verify_tls")
    connect_timeout = _int_range(
        merged["connect_timeout_seconds"], "connect_timeout_seconds", 1, 60
    )
    read_timeout = _int_range(
        merged["read_timeout_seconds"], "read_timeout_seconds", 1, 300
    )
    interval = _int_range(
        merged["collection_interval_seconds"],
        "collection_interval_seconds",
        10,
        3600,
    )
    server_url = validate_server_url(
        str(merged["server_url"]),
        verify_tls=verify_tls,
        loopback_test_profile=loopback_test_profile,
    )
    device_id = str(merged["device_id"])
    if not DEVICE_ID_RE.fullmatch(device_id):
        raise ClientContractError("device_id is invalid")
    device_name = _optional_text(merged.get("device_name"), "device_name", 128)
    fqdn = (
        normalize_fqdn(str(merged["device_fqdn"]))
        if merged.get("device_fqdn") not in (None, "")
        else None
    )
    token_file = validate_token_file_path(str(merged["token_file"]))
    return ClientV2Config(
        server_url=server_url,
        device_id=device_id,
        device_name=device_name,
        device_fqdn=fqdn,
        token_file=token_file,
        verify_tls=verify_tls,
        connect_timeout_seconds=connect_timeout,
        read_timeout_seconds=read_timeout,
        collection_interval_seconds=interval,
        loopback_test_profile=loopback_test_profile,
    )


def validate_server_url(
    value: str, *, verify_tls: bool, loopback_test_profile: bool
) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ClientContractError("server URL is invalid") from exc
    if parsed.username is not None or parsed.password is not None:
        raise ClientContractError("server URL must not contain credentials")
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ClientContractError("server URL must not contain query, fragment, or path prefix")
    if not parsed.hostname or port is not None and not 1 <= port <= 65535:
        raise ClientContractError("server URL host or port is invalid")
    host = parsed.hostname.lower()
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "https":
        if not verify_tls:
            raise ClientContractError("HTTPS requires TLS verification")
    elif not (parsed.scheme == "http" and loopback_test_profile and loopback):
        raise ClientContractError("production server URL must use HTTPS")
    return f"{parsed.scheme}://{parsed.netloc}"


def validate_token_file_path(value: str) -> str:
    if not value or len(value) > 4096 or "\x00" in value:
        raise ClientContractError("token_file path is invalid")
    path = PurePosixPath(value)
    if not path.is_absolute():
        raise ClientContractError("token_file must be an absolute path")
    return str(path)


def normalize_fqdn(value: str) -> str:
    normalized = value.strip().lower().removesuffix(".")
    if (
        not normalized
        or len(normalized.encode("utf-8")) > 253
        or any(char in normalized for char in "/*:@?#[]")
    ):
        raise ClientContractError("FQDN is invalid")
    labels = normalized.split(".")
    if len(labels) < 2 or any(not DNS_LABEL_RE.fullmatch(label) for label in labels):
        raise ClientContractError("FQDN is invalid")
    if all(part.isdigit() for part in labels):
        raise ClientContractError("FQDN must not be an IP literal")
    return normalized


def build_envelope(
    config: ClientV2Config,
    *,
    collected_at: str,
    stats: Mapping[str, Any],
    hostname: str | None = None,
) -> dict[str, Any]:
    _parse_rfc3339_utc(collected_at, "collected_at")
    if not isinstance(stats, Mapping) or not stats:
        raise ClientContractError("stats must be a non-empty object")
    device: dict[str, Any] = {"id": config.device_id}
    if config.device_name is not None:
        device["reported_name"] = config.device_name
    if config.device_fqdn is not None:
        device["reported_fqdn"] = config.device_fqdn
    if hostname is not None:
        device["hostname"] = _optional_text(hostname, "hostname", 253)
    envelope = {
        "schema_version": 2,
        "device": device,
        "collected_at": collected_at,
        "stats": dict(stats),
    }
    encoded = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode()
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise ClientContractError("envelope exceeds 1 MiB")
    forbidden = {
        "raw_response",
        "config",
        "order",
        "enabled",
        "stale_seconds",
        "offline_seconds",
        "ingestion",
        "token",
        "cookie",
        "password",
        "authorization",
        "private_key",
        "command",
        "device_json",
        "lucky_json",
    }
    found = forbidden.intersection(stats)
    if found:
        raise ClientContractError("stats contains forbidden fields")
    return envelope


def retry_delay_seconds(
    attempt: int,
    *,
    jitter_fraction: float,
    base_seconds: float = 3.0,
    cap_seconds: float = 300.0,
) -> float:
    if attempt < 0 or not 0.0 <= jitter_fraction <= 1.0:
        raise ClientContractError("retry arguments are invalid")
    ceiling = min(cap_seconds, base_seconds * math.pow(2.0, min(attempt, 30)))
    return ceiling * jitter_fraction


def _parse_rfc3339_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z") or len(value) > 40:
        raise ClientContractError(f"{field} must be RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ClientContractError(f"{field} must be RFC3339 UTC") from exc
    if parsed.tzinfo != timezone.utc:
        raise ClientContractError(f"{field} must be RFC3339 UTC")
    return parsed


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ClientContractError(f"{field} must be an object")
    return value


def _require_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ClientContractError(f"{field} fields do not match the contract")


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], field: str) -> None:
    if set(value) - allowed:
        raise ClientContractError(f"{field} contains unknown fields")


def _reject_ambiguous(value: Mapping[str, Any], field: str) -> None:
    if FORBIDDEN_AMBIGUOUS_KEYS.intersection(value):
        raise ClientContractError(f"{field} contains an ambiguous or plaintext-secret field")


def _bool_value(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ClientContractError(f"{field} must be a boolean")


def _int_range(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ClientContractError(f"{field} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ClientContractError(f"{field} must be an integer") from exc
    if str(number) != str(value) and not isinstance(value, int):
        raise ClientContractError(f"{field} must be an integer")
    if not minimum <= number <= maximum:
        raise ClientContractError(f"{field} is outside its allowed range")
    return number


def _optional_text(value: Any, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= maximum:
        raise ClientContractError(f"{field} is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ClientContractError(f"{field} is invalid")
    return value
