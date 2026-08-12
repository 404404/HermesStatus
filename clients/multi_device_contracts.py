"""Pure HermesStatus 2.2 Client contracts.

This Stage A module performs no network I/O, DNS, TLS, token-file reads, or
production entrypoint integration.
"""

from __future__ import annotations

import json
import ipaddress
import math
import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol
from urllib.parse import unquote, urlsplit


DEVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
MAX_ENVELOPE_BYTES = 1 << 20
MAX_RESPONSE_BYTES = 1 << 20
UPDATE_PATH = "/api/v2/device-updates"
REQUIRED_STATS_FIELDS = {
    "extension_version",
    "hardware",
    "docker",
    "hermes",
    "lucky",
}
ALLOWED_STATS_FIELDS = {
    "uptime",
    "load_1",
    "load_5",
    "load_15",
    "ping_10010",
    "ping_189",
    "ping_10086",
    "time_10010",
    "time_189",
    "time_10086",
    "tcp",
    "udp",
    "process",
    "thread",
    "network_rx",
    "network_tx",
    "network_in",
    "network_out",
    "memory_total",
    "memory_used",
    "swap_total",
    "swap_used",
    "hdd_total",
    "hdd_used",
    "io_read",
    "io_write",
    "cpu",
    "cpu_cores",
    "cpu_model",
    "custom",
    "os",
    "online4",
    "online6",
    "extension_version",
    "hardware",
    "docker",
    "hermes",
    "lucky",
    "easytier",
    "client_build",
    "hardware_json",
    "docker_json",
    "hermes_json",
}
ALLOWED_MONITOR_TYPES = {"http", "https", "tcp"}
SAFE_GENERATION_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"
)
SMART_DEVICE_PATH_RE = re.compile(r"^/dev/[A-Za-z0-9][A-Za-z0-9._+-]{0,126}$")
SMART_DEVICE_TYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9,._+-]{0,63}$")

ENV_TO_FIELD = {
    "HERMESSTATUS_SERVER_URL": "server_url",
    "HERMESSTATUS_DEVICE_ID": "device_id",
    "HERMESSTATUS_DEVICE_NAME": "device_name",
    "HERMESSTATUS_DEVICE_FQDN": "device_fqdn",
    "HERMESSTATUS_DEVICE_TOKEN_FILE": "token_file",
    "HERMESSTATUS_TLS_CA_FILE": "ca_file",
    "HERMESSTATUS_TLS_VERIFY": "verify_tls",
    "HERMESSTATUS_CONNECT_TIMEOUT_SECONDS": "connect_timeout_seconds",
    "HERMESSTATUS_READ_TIMEOUT_SECONDS": "read_timeout_seconds",
    "HERMESSTATUS_COLLECTION_INTERVAL_SECONDS": "collection_interval_seconds",
    "HERMESSTATUS_SMART_DEVICES": "smart_devices",
    "HERMESSTATUS_PRIMARY_SMART_DEVICE": "primary_smart_device",
    "HERMESSTATUS_FILESYSTEM_PROBES": "filesystem_probes",
}
ALLOWED_FIELDS = {
    "server_url",
    "device_id",
    "device_name",
    "device_fqdn",
    "token_file",
    "ca_file",
    "verify_tls",
    "connect_timeout_seconds",
    "read_timeout_seconds",
    "collection_interval_seconds",
    "smart_devices",
    "primary_smart_device",
    "filesystem_probes",
}
FORBIDDEN_AMBIGUOUS_KEYS = {"DOMAIN", "TOKEN", "PASSWORD", "AUTHORIZATION"}


class ClientContractError(ValueError):
    """A sanitized configuration or envelope contract failure."""


@dataclass(frozen=True)
class SmartDeviceConfig:
    path: str
    type: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class FilesystemProbeConfig:
    mountpoint: str
    probe_path: str


@dataclass(frozen=True)
class ClientV2Config:
    server_url: str
    device_id: str
    device_name: str | None
    device_fqdn: str | None
    token_file: str
    ca_file: str | None = None
    verify_tls: bool = True
    connect_timeout_seconds: int = 10
    read_timeout_seconds: int = 30
    collection_interval_seconds: int = 60
    smart_devices: tuple[SmartDeviceConfig, ...] | None = None
    primary_smart_device: str | None = None
    filesystem_probes: tuple[FilesystemProbeConfig, ...] = ()
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
        document = json.loads(data, object_pairs_hook=_strict_object)
    except (TypeError, json.JSONDecodeError, ClientContractError) as exc:
        raise ClientContractError("config is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ClientContractError("config root must be an object")
    _require_fields(
        document,
        {"version", "server", "device", "collection"},
        {"hardware"},
        "config",
    )
    if document["version"] != 1:
        raise ClientContractError("config.version must equal 1")
    server = _object(document["server"], "server")
    device = _object(document["device"], "device")
    collection = _object(document["collection"], "collection")
    _require_fields(
        server,
        {"url", "verify_tls", "connect_timeout_seconds", "read_timeout_seconds"},
        {"ca_file"},
        "server",
    )
    _require_keys(device, {"id", "name", "fqdn", "token_file"}, "device")
    _require_keys(collection, {"interval_seconds"}, "collection")
    values = {
        "server_url": server["url"],
        "verify_tls": server["verify_tls"],
        "connect_timeout_seconds": server["connect_timeout_seconds"],
        "read_timeout_seconds": server["read_timeout_seconds"],
        "ca_file": server.get("ca_file"),
        "device_id": device["id"],
        "device_name": device["name"],
        "device_fqdn": device["fqdn"],
        "token_file": device["token_file"],
        "collection_interval_seconds": collection["interval_seconds"],
    }
    if "hardware" in document:
        hardware = _object(document["hardware"], "hardware")
        _require_fields(
            hardware,
            set(),
            {"smart_devices", "primary_smart_device", "filesystem_probes"},
            "hardware",
        )
        for key in ("smart_devices", "primary_smart_device", "filesystem_probes"):
            if key in hardware:
                values[key] = hardware[key]
    return values


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
    # SMART_DEVICE predates device_v2.  Keep it as the lowest-priority
    # environment spelling while allowing explicit plural JSON configuration
    # to override the config file without reopening unrestricted /dev access.
    for field, names in {
        "smart_devices": (
            "HERMESSTATUS_SMART_DEVICES", "SMART_DEVICES", "SMART_DEVICE",
        ),
        "primary_smart_device": (
            "HERMESSTATUS_PRIMARY_SMART_DEVICE", "PRIMARY_SMART_DEVICE",
        ),
        "filesystem_probes": (
            "HERMESSTATUS_FILESYSTEM_PROBES", "FILESYSTEM_PROBES",
        ),
    }.items():
        for name in names:
            value = env.get(name)
            if value not in (None, ""):
                # The container image's SMART_DEVICE=auto is a legacy
                # automatic-discovery sentinel, not an explicit Device v2
                # allowlist.  It must not override a JSON allowlist (including
                # an intentional empty list) from the config file.
                if name == "SMART_DEVICE" and isinstance(value, str) and value.strip().lower() == "auto":
                    continue
                env_values[field] = value
                break

    merged: dict[str, Any] = {
        "verify_tls": True,
        "connect_timeout_seconds": 10,
        "read_timeout_seconds": 30,
        "collection_interval_seconds": 60,
        "device_name": None,
        "device_fqdn": None,
        "ca_file": None,
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
    try:
        ipaddress.ip_address(device_id)
        device_id_is_ip = True
    except ValueError:
        device_id_is_ip = False
    if not DEVICE_ID_RE.fullmatch(device_id) or device_id_is_ip:
        raise ClientContractError("device_id is invalid")
    device_name = _optional_text(merged.get("device_name"), "device_name", 128)
    fqdn = (
        normalize_fqdn(str(merged["device_fqdn"]))
        if merged.get("device_fqdn") not in (None, "")
        else None
    )
    token_file = validate_token_file_path(str(merged["token_file"]))
    ca_file = (
        validate_readonly_file_path(str(merged["ca_file"]), "ca_file")
        if merged.get("ca_file") not in (None, "")
        else None
    )
    smart_devices = _smart_devices_value(merged.get("smart_devices"))
    primary_smart_device = _smart_device_path(
        merged.get("primary_smart_device"), "primary_smart_device", optional=True
    )
    if primary_smart_device and smart_devices is not None and not any(
        device.path == primary_smart_device for device in smart_devices
    ):
        raise ClientContractError("primary_smart_device is not configured")
    filesystem_probes = _filesystem_probes_value(merged.get("filesystem_probes"))
    return ClientV2Config(
        server_url=server_url,
        device_id=device_id,
        device_name=device_name,
        device_fqdn=fqdn,
        token_file=token_file,
        ca_file=ca_file,
        verify_tls=verify_tls,
        connect_timeout_seconds=connect_timeout,
        read_timeout_seconds=read_timeout,
        collection_interval_seconds=interval,
        smart_devices=smart_devices,
        primary_smart_device=primary_smart_device,
        filesystem_probes=filesystem_probes,
        loopback_test_profile=loopback_test_profile,
    )


def _json_value(value: Any, field: str) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value, object_pairs_hook=_strict_object)
    except (TypeError, json.JSONDecodeError, ClientContractError) as exc:
        raise ClientContractError(f"{field} is invalid") from exc


def _smart_device_path(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not SMART_DEVICE_PATH_RE.fullmatch(value):
        raise ClientContractError(f"{field} is invalid")
    return value


def _smart_devices_value(value: Any) -> tuple[SmartDeviceConfig, ...] | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == "auto":
        # Preserve the legacy automatic-discovery alias when it reaches this
        # parser through a compatible environment spelling or CLI override.
        return None
    if isinstance(value, str) and value.strip().startswith("/dev/"):
        return (SmartDeviceConfig(path=_smart_device_path(value, "smart_devices")),)
    if isinstance(value, str) and not value.lstrip().startswith("["):
        try:
            parts = shlex.split(value)
        except ValueError as exc:
            raise ClientContractError("smart_devices is invalid") from exc
        if parts and "-d" in parts:
            position = parts.index("-d")
            device_type = parts[position + 1] if position + 1 < len(parts) else None
            path = next((part for part in parts if part.startswith("/dev/")), None)
            if path and device_type:
                return (
                    SmartDeviceConfig(
                        path=_smart_device_path(path, "smart_devices"),
                        type=_smart_device_type(device_type),
                    ),
                )
    entries = _json_value(value, "smart_devices")
    if not isinstance(entries, list) or len(entries) > 64:
        raise ClientContractError("smart_devices is invalid")
    devices = []
    paths = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"path", "type", "label"} or "path" not in entry:
            raise ClientContractError("smart_devices is invalid")
        path = _smart_device_path(entry["path"], "smart_devices.path")
        device_type = _optional_text(entry.get("type"), "smart_devices.type", 64)
        if device_type is not None:
            device_type = _smart_device_type(device_type)
        label = _optional_text(entry.get("label"), "smart_devices.label", 128)
        if path in paths:
            raise ClientContractError("smart_devices contains duplicate paths")
        paths.add(path)
        devices.append(SmartDeviceConfig(path=path, type=device_type, label=label))
    return tuple(devices)


def _smart_device_type(value: str) -> str:
    if not SMART_DEVICE_TYPE_RE.fullmatch(value):
        raise ClientContractError("smart_devices.type is invalid")
    return value


def _safe_probe_path(value: Any, field: str, *, maximum_length: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum_length or "\x00" in value:
        raise ClientContractError(f"{field} is invalid")
    path = PurePosixPath(value)
    if not path.is_absolute() or str(path) != value or ".." in path.parts:
        raise ClientContractError(f"{field} is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ClientContractError(f"{field} is invalid")
    return value


def _filesystem_probes_value(value: Any) -> tuple[FilesystemProbeConfig, ...]:
    if value is None:
        return ()
    entries = _json_value(value, "filesystem_probes")
    if not isinstance(entries, list) or len(entries) > 128:
        raise ClientContractError("filesystem_probes is invalid")
    probes = []
    mountpoints = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"mountpoint", "probe_path"}:
            raise ClientContractError("filesystem_probes is invalid")
        mountpoint = _safe_probe_path(
            entry["mountpoint"], "filesystem_probes.mountpoint", maximum_length=512
        )
        probe_path = _safe_probe_path(entry["probe_path"], "filesystem_probes.probe_path")
        if mountpoint in mountpoints:
            raise ClientContractError("filesystem_probes contains duplicate mountpoints")
        mountpoints.add(mountpoint)
        probes.append(FilesystemProbeConfig(mountpoint=mountpoint, probe_path=probe_path))
    return tuple(probes)


def validate_server_url(
    value: str, *, verify_tls: bool, loopback_test_profile: bool
) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= 2048
        or any(ord(char) < 0x21 or ord(char) == 0x7F for char in value)
        or "\\" in value
    ):
        raise ClientContractError("server URL is invalid")
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
    if not _safe_network_host(host):
        raise ClientContractError("server URL host or port is invalid")
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "https":
        if not verify_tls:
            raise ClientContractError("HTTPS requires TLS verification")
    elif not (parsed.scheme == "http" and loopback_test_profile and loopback):
        raise ClientContractError("production server URL must use HTTPS")
    return f"{parsed.scheme}://{parsed.netloc}"


def validate_token_file_path(value: str) -> str:
    return validate_readonly_file_path(value, "token_file")


def validate_readonly_file_path(value: str, field: str) -> str:
    if not value or len(value) > 4096 or "\x00" in value:
        raise ClientContractError(f"{field} path is invalid")
    path = PurePosixPath(value)
    if not path.is_absolute():
        raise ClientContractError(f"{field} must be an absolute path")
    if str(path) != value or ".." in path.parts:
        raise ClientContractError(f"{field} path is invalid")
    return str(path)


def normalize_fqdn(value: str) -> str:
    if value != value.strip():
        raise ClientContractError("FQDN is invalid")
    normalized = value.lower()
    if normalized.endswith("."):
        normalized = normalized[:-1]
    if (
        not normalized
        or len(normalized.encode("utf-8")) > 253
        or any(char in normalized for char in "/*:@?#[]")
    ):
        raise ClientContractError("FQDN is invalid")
    labels = normalized.split(".")
    if len(labels) < 2 or any(not DNS_LABEL_RE.fullmatch(label) for label in labels):
        raise ClientContractError("FQDN is invalid")
    try:
        ipaddress.ip_address(normalized)
        is_ip = True
    except ValueError:
        is_ip = False
    if is_ip:
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
    if not REQUIRED_STATS_FIELDS.issubset(stats):
        raise ClientContractError("stats is missing required fields")
    if set(stats) - ALLOWED_STATS_FIELDS:
        raise ClientContractError("stats contains unknown fields")
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
    found.update(
        _find_forbidden_fields(
            stats,
            {
                "raw_response",
                "token",
                "cookie",
                "password",
                "authorization",
                "private_key",
                "command",
                "device_json",
                "lucky_json",
            },
        )
    )
    if found:
        raise ClientContractError("stats contains forbidden fields")
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
    try:
        encoded = json.dumps(
            envelope,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ClientContractError("envelope is not JSON serializable") from exc
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise ClientContractError("envelope exceeds 1 MiB")
    return envelope


def encode_envelope(envelope: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            envelope,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ClientContractError("envelope is not JSON serializable") from exc
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise ClientContractError("envelope exceeds 1 MiB")
    return encoded


def validate_success_response(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or set(document) != {
        "accepted",
        "server_time",
        "config_generation",
        "monitors",
    }:
        raise ClientContractError("server response fields are invalid")
    if document["accepted"] is not True:
        raise ClientContractError("server response was not accepted")
    _parse_rfc3339_utc(document["server_time"], "server_time")
    generation = document["config_generation"]
    if not isinstance(generation, str) or not SAFE_GENERATION_RE.fullmatch(generation):
        raise ClientContractError("config_generation is invalid")
    monitors = document["monitors"]
    if not isinstance(monitors, list) or len(monitors) > 256:
        raise ClientContractError("monitors are invalid")
    validated = [validate_monitor(monitor) for monitor in monitors]
    return {
        "accepted": True,
        "server_time": document["server_time"],
        "config_generation": generation,
        "monitors": validated,
    }


def decode_success_response(data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes) or not data or len(data) > MAX_RESPONSE_BYTES:
        raise ClientContractError("server response size is invalid")
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ClientContractError) as exc:
        raise ClientContractError("server response is not valid JSON") from exc
    return validate_success_response(document)


def validate_monitor(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "name",
        "host",
        "interval",
        "type",
    }:
        raise ClientContractError("monitor fields are invalid")
    name = _required_text(value["name"], "monitor.name", 128)
    monitor_type = value["type"]
    if not isinstance(monitor_type, str) or monitor_type not in ALLOWED_MONITOR_TYPES:
        raise ClientContractError("monitor type is invalid")
    interval = _int_range(value["interval"], "monitor.interval", 1, 86400)
    host = _validate_monitor_host(value["host"], monitor_type)
    return {
        "name": name,
        "host": host,
        "interval": interval,
        "type": monitor_type,
    }


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
    if (
        not isinstance(value, str)
        or len(value) > 40
        or not RFC3339_UTC_RE.fullmatch(value)
    ):
        raise ClientContractError(f"{field} must be RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
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


def _require_fields(
    value: Mapping[str, Any],
    required: set[str],
    optional: set[str],
    field: str,
) -> None:
    actual = set(value)
    if not required.issubset(actual) or actual - required - optional:
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


def _required_text(value: Any, field: str, maximum: int) -> str:
    result = _optional_text(value, field, maximum)
    if result is None:
        raise ClientContractError(f"{field} is invalid")
    return result


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ClientContractError("JSON object contains a duplicate field")
        result[key] = value
    return result


def _find_forbidden_fields(value: Any, forbidden: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in forbidden:
                found.add(str(key).lower())
            found.update(_find_forbidden_fields(child, forbidden))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.update(_find_forbidden_fields(child, forbidden))
    return found


def _validate_monitor_host(value: Any, monitor_type: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= 253:
        raise ClientContractError("monitor host is invalid")
    if any(ord(char) < 33 or ord(char) == 127 for char in value) or "\\" in value:
        raise ClientContractError("monitor host is invalid")
    if monitor_type == "tcp":
        host, separator, port_text = value.rpartition(":")
        if not separator or not host or not port_text.isdigit():
            raise ClientContractError("monitor host is invalid")
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        elif ":" in host:
            raise ClientContractError("monitor host is invalid")
        if not _safe_network_host(host) or not 1 <= int(port_text) <= 65535:
            raise ClientContractError("monitor host is invalid")
        return value
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ClientContractError("monitor host is invalid") from exc
    if (
        parsed.scheme != monitor_type
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or "?" in value
        or port is not None
        and not 1 <= port <= 65535
        or not _safe_network_host(parsed.hostname)
        or any(segment == ".." for segment in unquote(parsed.path).split("/"))
    ):
        raise ClientContractError("monitor host is invalid")
    return value


def _safe_network_host(value: str) -> bool:
    if not value or len(value) > 253 or "%" in value:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    labels = value.split(".")
    return all(
        1 <= len(label) <= 63
        and label[0] != "-"
        and label[-1] != "-"
        and all(char.isascii() and (char.isalnum() or char == "-") for char in label)
        for label in labels
    )
