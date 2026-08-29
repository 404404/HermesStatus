"""Strict HermesStatus 2.5 unified Client configuration.

The unified file is a secret bundle for downstream collectors.  Device v2
authentication remains a separate, fixed token file.  This module validates
the bounded JSON shape and materializes only the collector secrets into the
Client's ephemeral tmpfs; values are never placed in argv or environment.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
CANONICAL_DEVICE_TOKEN_PATH = "/run/secrets/hermesstatus-device-token"
MAX_CONFIG_BYTES = 128 << 10
MAX_SECRET_BYTES = 4096
ALLOWED_PLATFORMS = {"linux", "synology", "macos", "windows"}
COLLECTOR_NAMES = (
    "hardware", "filesystem", "smart", "docker", "hermes", "lucky",
    "easytier", "unifi",
)
EASYTIER_ROLES = {"site_router", "endpoint", "bootstrap_listener", "relay_capable", "observer"}
EASYTIER_CLI_PATHS = {
    "/usr/local/bin/easytier-cli",
    "/usr/local/libexec/hermesstatus/easytier-cli",
}
SECRET_KEYS = {"open_token", "ssh_password", "password", "api_key"}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _error(message: str):
    from multi_device_contracts import ClientContractError

    raise ClientContractError(message)


def _obj(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _error(f"{field} must be an object")
    return value


def _fields(value: Mapping[str, Any], required: set[str], optional: set[str], field: str) -> None:
    actual = set(value)
    if not required.issubset(actual) or actual - required - optional:
        _error(f"{field} fields do not match the contract")


def _string(value: Any, field: str, maximum: int = 4096, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        _error(f"{field} is invalid")
    if nonempty and not value:
        _error(f"{field} is required")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        _error(f"{field} is invalid")
    return value


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        _error(f"{field} must be a boolean")
    return value


def _int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _error(f"{field} is invalid")
    return value


def _path(value: Any, field: str, maximum: int = 4096) -> str:
    from multi_device_contracts import validate_readonly_file_path

    try:
        return validate_readonly_file_path(_string(value, field, maximum), field)
    except Exception:
        _error(f"{field} is invalid")


def _validate_known_hosts(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 16:
        _error("collectors.unifi.ssh.known_hosts is invalid")
    result = []
    for line in value:
        text = _string(line, "collectors.unifi.ssh.known_hosts", 1024)
        if " " not in text or text.startswith("#") or "\n" in text or "\r" in text:
            _error("collectors.unifi.ssh.known_hosts is invalid")
        result.append(text)
    return result


def _validate_enabled_only(value: Any, field: str) -> bool:
    value = _obj(value, field)
    _fields(value, {"enabled"}, set(), field)
    return _bool(value["enabled"], f"{field}.enabled")


def _validate_filesystem(value: Any) -> tuple[bool, list[dict[str, str]]]:
    value = _obj(value, "collectors.filesystem")
    _fields(value, {"enabled"}, {"probes"}, "collectors.filesystem")
    enabled = _bool(value["enabled"], "collectors.filesystem.enabled")
    if not enabled:
        if set(value) != {"enabled"}:
            _error("disabled collectors.filesystem must not contain target fields")
        return False, []
    probes = value.get("probes", [])
    if not isinstance(probes, list) or len(probes) > 16:
        _error("collectors.filesystem.probes is invalid")
    result = []
    seen = set()
    for index, entry in enumerate(probes):
        entry = _obj(entry, f"collectors.filesystem.probes[{index}]")
        _fields(entry, {"mountpoint", "probe_path"}, set(), f"collectors.filesystem.probes[{index}]")
        mountpoint = _string(entry["mountpoint"], "collectors.filesystem.probes.mountpoint", 512)
        probe_path = _string(entry["probe_path"], "collectors.filesystem.probes.probe_path", 4096)
        if not mountpoint.startswith("/") or not probe_path.startswith("/") or ".." in mountpoint.split("/") or ".." in probe_path.split("/"):
            _error("collectors.filesystem.probes path is invalid")
        if mountpoint in seen:
            _error("collectors.filesystem.probes contains duplicate mountpoints")
        seen.add(mountpoint)
        result.append({"mountpoint": mountpoint, "probe_path": probe_path})
    return True, result


def _validate_smart(value: Any) -> tuple[bool, list[dict[str, Any]], str | None]:
    value = _obj(value, "collectors.smart")
    _fields(value, {"enabled"}, {"devices", "primary_device"}, "collectors.smart")
    enabled = _bool(value["enabled"], "collectors.smart.enabled")
    if not enabled:
        if set(value) != {"enabled"}:
            _error("disabled collectors.smart must not contain target fields")
        return False, [], None
    entries = value.get("devices", [])
    if not isinstance(entries, list) or len(entries) > 64:
        _error("collectors.smart.devices is invalid")
    devices = []
    paths = set()
    for index, entry in enumerate(entries):
        entry = _obj(entry, f"collectors.smart.devices[{index}]")
        _fields(entry, {"path"}, {"type", "label"}, f"collectors.smart.devices[{index}]")
        path = _string(entry["path"], "collectors.smart.devices.path", 132)
        if not re.fullmatch(r"/dev/[A-Za-z0-9][A-Za-z0-9._+-]{0,126}", path) or path in paths:
            _error("collectors.smart.devices.path is invalid")
        paths.add(path)
        item = {"path": path, "type": entry.get("type"), "label": entry.get("label")}
        if item["type"] is not None:
            item["type"] = _string(item["type"], "collectors.smart.devices.type", 64)
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9,._+-]{0,63}", item["type"]):
                _error("collectors.smart.devices.type is invalid")
        if item["label"] is not None:
            item["label"] = _string(item["label"], "collectors.smart.devices.label", 128)
        devices.append(item)
    primary = value.get("primary_device")
    if primary is not None:
        primary = _string(primary, "collectors.smart.primary_device", 132)
        if primary not in paths:
            _error("collectors.smart.primary_device is not configured")
    return True, devices, primary


def _validate_lucky(value: Any) -> tuple[dict[str, Any], bool]:
    value = _obj(value, "collectors.lucky")
    enabled = _bool(value.get("enabled"), "collectors.lucky.enabled") if "enabled" in value else _error("collectors.lucky.enabled is required")
    if not enabled:
        if set(value) != {"enabled"}:
            _error("disabled collectors.lucky must not contain target fields")
        return {"enabled": False}, False
    required = {"enabled", "base_url", "auth_mode", "verify_tls", "timeout_seconds", "warning_days", "version_check_ttl"}
    optional = {"open_token"}
    _fields(value, required, optional, "collectors.lucky")
    base_url = _string(value["base_url"], "collectors.lucky.base_url", 2048)
    from urllib.parse import urlsplit
    parsed = urlsplit(base_url)
    try:
        lucky_port = parsed.port
    except ValueError:
        _error("collectors.lucky.base_url is invalid")
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in ("", "/")
        or (lucky_port is not None and not 1 <= lucky_port <= 65535)
    ):
        _error("collectors.lucky.base_url is invalid")
    auth_mode = _string(value["auth_mode"], "collectors.lucky.auth_mode", 32).lower()
    if auth_mode not in {"none", "open_token", "admin_token"}:
        _error("collectors.lucky.auth_mode is invalid")
    verify_tls = _bool(value["verify_tls"], "collectors.lucky.verify_tls")
    timeout = _int(value["timeout_seconds"], "collectors.lucky.timeout_seconds", 1, 30)
    warning_days = _int(value["warning_days"], "collectors.lucky.warning_days", 1, 365)
    version_ttl = _int(value["version_check_ttl"], "collectors.lucky.version_check_ttl", 3600, 86400)
    token = value.get("open_token")
    if auth_mode != "none":
        token = _string(token, "collectors.lucky.open_token", MAX_SECRET_BYTES)
    elif token is not None:
        _error("collectors.lucky.open_token is not allowed when auth_mode=none")
    return {
        "enabled": True, "base_url": base_url, "auth_mode": auth_mode,
        "verify_tls": verify_tls, "timeout_seconds": timeout,
        "warning_days": warning_days, "version_check_ttl": version_ttl,
        **({"open_token": token} if token is not None else {}),
    }, True


def _validate_easytier(value: Any) -> dict[str, Any]:
    value = _obj(value, "collectors.easytier")
    enabled = _bool(value.get("enabled"), "collectors.easytier.enabled") if "enabled" in value else _error("collectors.easytier.enabled is required")
    if not enabled:
        if set(value) != {"enabled"}:
            _error("disabled collectors.easytier must not contain target fields")
        return {"enabled": False}
    required = {"enabled", "cli_path", "rpc_portal", "timeout_seconds", "interval_seconds", "administrative_role"}
    _fields(value, required, set(), "collectors.easytier")
    cli_path = _string(value["cli_path"], "collectors.easytier.cli_path", 256)
    if cli_path not in EASYTIER_CLI_PATHS:
        _error("collectors.easytier.cli_path is not an allowed bridge")
    rpc = _string(value["rpc_portal"], "collectors.easytier.rpc_portal", 64)
    if rpc != "127.0.0.1:15888":
        _error("collectors.easytier.rpc_portal is not the fixed loopback RPC")
    role = value["administrative_role"]
    if role not in (None, "", *EASYTIER_ROLES):
        _error("collectors.easytier.administrative_role is invalid")
    return {
        "enabled": True, "cli_path": cli_path, "rpc_portal": rpc,
        "timeout_seconds": _int(value["timeout_seconds"], "collectors.easytier.timeout_seconds", 1, 30),
        "interval_seconds": _int(value["interval_seconds"], "collectors.easytier.interval_seconds", 5, 3600),
        "administrative_role": role or None,
    }


def _validate_unifi(value: Any) -> tuple[dict[str, Any], bool]:
    value = _obj(value, "collectors.unifi")
    enabled = _bool(value.get("enabled"), "collectors.unifi.enabled") if "enabled" in value else _error("collectors.unifi.enabled is required")
    if not enabled:
        if set(value) != {"enabled"}:
            _error("disabled collectors.unifi must not contain target fields")
        return {"enabled": False}, False
    _fields(value, {"enabled", "profile", "host", "port", "interval_seconds", "ssh", "api"}, set(), "collectors.unifi")
    profile = _string(value["profile"], "collectors.unifi.profile", 32)
    if profile not in {"udw", "ucg-max"}:
        _error("collectors.unifi.profile is invalid")
    host = _string(value["host"], "collectors.unifi.host", 253)
    from multi_device_contracts import _safe_network_host
    if not _safe_network_host(host.lower()):
        _error("collectors.unifi.host is invalid")
    ssh = _obj(value["ssh"], "collectors.unifi.ssh")
    ssh_enabled = _bool(ssh.get("enabled"), "collectors.unifi.ssh.enabled") if "enabled" in ssh else _error("collectors.unifi.ssh.enabled is required")
    if ssh_enabled:
        _fields(ssh, {"enabled", "username", "password", "known_hosts", "port"}, set(), "collectors.unifi.ssh")
        username = _string(ssh["username"], "collectors.unifi.ssh.username", 32)
        if not _USER_RE.fullmatch(username):
            _error("collectors.unifi.ssh.username is invalid")
        ssh_value = _string(ssh["password"], "collectors.unifi.ssh.password", MAX_SECRET_BYTES)
        known_hosts = _validate_known_hosts(ssh["known_hosts"])
        ssh_port = _int(ssh["port"], "collectors.unifi.ssh.port", 1, 65535)
    else:
        if set(ssh) != {"enabled"}:
            _error("disabled collectors.unifi.ssh must not contain target fields")
        username = ssh_value = None
        known_hosts = []
        ssh_port = 22
    api = _obj(value["api"], "collectors.unifi.api")
    api_enabled = _bool(api.get("enabled"), "collectors.unifi.api.enabled") if "enabled" in api else _error("collectors.unifi.api.enabled is required")
    if not ssh_enabled and not api_enabled:
        _error("collectors.unifi requires at least one enabled transport")
    if api_enabled and not ssh_enabled:
        _error("collectors.unifi.ssh is required when collectors.unifi.api is enabled")
    if api_enabled:
        _fields(api, {"enabled", "base_url", "api_key", "tls_sha256", "timeout_seconds"}, {"site_id"}, "collectors.unifi.api")
        base_url = _string(api["base_url"], "collectors.unifi.api.base_url", 2048)
        from urllib.parse import urlsplit
        parsed = urlsplit(base_url)
        try:
            api_port = parsed.port
        except ValueError:
            _error("collectors.unifi.api.base_url is invalid")
        if api_port is not None and not 1 <= api_port <= 65535:
            _error("collectors.unifi.api.base_url is invalid")
        if parsed.scheme != "https" or parsed.hostname is None or parsed.hostname.lower() != host.lower() or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            _error("collectors.unifi.api.base_url is invalid")
        api_value = _string(api["api_key"], "collectors.unifi.api.api_key", MAX_SECRET_BYTES)
        fingerprint = _string(api["tls_sha256"], "collectors.unifi.api.tls_sha256", 64)
        if not _FINGERPRINT_RE.fullmatch(fingerprint):
            _error("collectors.unifi.api.tls_sha256 is invalid")
        api_timeout = _int(api["timeout_seconds"], "collectors.unifi.api.timeout_seconds", 3, 30)
        site_id = api.get("site_id")
        if site_id is not None:
            site_id = _string(site_id, "collectors.unifi.api.site_id", 128)
            if not _ID_RE.fullmatch(site_id):
                _error("collectors.unifi.api.site_id is invalid")
    else:
        if set(api) != {"enabled"}:
            _error("disabled collectors.unifi.api must not contain target fields")
        base_url = api_value = fingerprint = None
        api_timeout = 5
        site_id = None
    return {
        "enabled": True, "profile": profile, "host": host,
        "port": _int(value["port"], "collectors.unifi.port", 1, 65535),
        "interval_seconds": _int(value["interval_seconds"], "collectors.unifi.interval_seconds", 30, 180),
        "ssh": {"enabled": ssh_enabled, "username": username, "password": ssh_value, "known_hosts": known_hosts, "port": ssh_port},
        "api": {"enabled": api_enabled, "base_url": base_url, "api_key": api_value, "tls_sha256": fingerprint, "timeout_seconds": api_timeout, **({"site_id": site_id} if site_id is not None else {})},
    }, True


def parse_unified_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a unified config and return values for the existing ClientV2Config resolver."""
    document = _obj(document, "config")
    _fields(document, {"schema_version", "server", "device", "collectors"}, {"collection"}, "config")
    if document["schema_version"] != SCHEMA_VERSION:
        _error("config.schema_version is unsupported")
    server = _obj(document["server"], "server")
    _fields(server, {"url", "verify_tls", "connect_timeout_seconds", "read_timeout_seconds"}, {"ca_file"}, "server")
    from multi_device_contracts import validate_server_url
    verify_tls = _bool(server["verify_tls"], "server.verify_tls")
    values: dict[str, Any] = {
        "server_url": validate_server_url(str(server["url"]), verify_tls=verify_tls, loopback_test_profile=False),
        "verify_tls": verify_tls,
        "connect_timeout_seconds": _int(server["connect_timeout_seconds"], "server.connect_timeout_seconds", 1, 60),
        "read_timeout_seconds": _int(server["read_timeout_seconds"], "server.read_timeout_seconds", 1, 300),
        "ca_file": _path(server["ca_file"], "server.ca_file") if server.get("ca_file") not in (None, "") else None,
    }
    device = _obj(document["device"], "device")
    _fields(device, {"id", "display_name", "platform"}, {"fqdn"}, "device")
    device_id = _string(device["id"], "device.id", 63)
    if not _ID_RE.fullmatch(device_id):
        _error("device.id is invalid")
    display_name = _string(device["display_name"], "device.display_name", 128)
    platform = _string(device["platform"], "device.platform", 16)
    if platform not in ALLOWED_PLATFORMS:
        _error("device.platform is invalid")
    collection = document.get("collection", {"interval_seconds": 60})
    collection = _obj(collection, "collection")
    _fields(collection, {"interval_seconds"}, set(), "collection")
    collection_interval = _int(collection["interval_seconds"], "collection.interval_seconds", 10, 3600)
    values.update({
        "device_id": device_id, "device_name": display_name,
        "device_fqdn": device.get("fqdn"),
        "token_file": CANONICAL_DEVICE_TOKEN_PATH,
        "platform": platform,
        "collection_interval_seconds": collection_interval,
    })
    collectors = _obj(document["collectors"], "collectors")
    if set(collectors) != set(COLLECTOR_NAMES):
        _error("collectors fields do not match the contract")
    hardware_enabled = _validate_enabled_only(collectors["hardware"], "collectors.hardware")
    filesystem_enabled, filesystem_probes = _validate_filesystem(collectors["filesystem"])
    smart_enabled, smart_devices, primary = _validate_smart(collectors["smart"])
    if not hardware_enabled and (filesystem_enabled or smart_enabled):
        _error("collectors.hardware.enabled must be true when filesystem or smart is enabled")
    docker_enabled = _validate_enabled_only(collectors["docker"], "collectors.docker")
    hermes_enabled = _validate_enabled_only(collectors["hermes"], "collectors.hermes")
    lucky, _ = _validate_lucky(collectors["lucky"])
    easytier = _validate_easytier(collectors["easytier"])
    unifi, _ = _validate_unifi(collectors["unifi"])
    values.update({
        "smart_devices": smart_devices if smart_enabled else [],
        "primary_smart_device": primary,
        "filesystem_probes": filesystem_probes if filesystem_enabled else [],
        "unified_collectors": {
            "hardware": {"enabled": hardware_enabled},
            "filesystem": {"enabled": filesystem_enabled, "probes": filesystem_probes},
            "smart": {"enabled": smart_enabled},
            "docker": {"enabled": docker_enabled},
            "hermes": {"enabled": hermes_enabled},
            "lucky": lucky,
            "easytier": easytier,
            "unifi": unifi,
        },
    })
    return values


def materialize_unified_collectors(collectors: Mapping[str, Any], root: str = "/run/hermesstatus") -> dict[str, Any]:
    """Materialize validated secret values into fixed private tmpfs paths."""
    root_path = Path(root)
    root_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root_path, 0o700)
    created: list[Path] = []

    def write_secret(relative: str, value: str) -> str:
        path = root_path / relative
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(path, flags, 0o600)
        try:
            os.write(descriptor, value.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(path, 0o600)
        created.append(path)
        return str(path)

    try:
        runtime: dict[str, Any] = {}
        lucky = dict(collectors.get("lucky") or {})
        if lucky.get("enabled") and lucky.get("auth_mode") != "none":
            lucky["token_file"] = write_secret("lucky/open-token", lucky.pop("open_token"))
        else:
            lucky.pop("open_token", None)
        runtime["lucky"] = lucky
        runtime["easytier"] = dict(collectors.get("easytier") or {})
        unifi = dict(collectors.get("unifi") or {})
        if unifi.get("enabled"):
            ssh = dict(unifi.get("ssh") or {})
            if ssh.get("enabled"):
                ssh["credential_file"] = write_secret("unifi/password", ssh.pop("password"))
                ssh["known_hosts_file"] = write_secret("unifi/known_hosts", "\n".join(ssh.pop("known_hosts")) + "\n")
            unifi["ssh"] = ssh
            api = dict(unifi.get("api") or {})
            if api.get("enabled"):
                api["api_key_file"] = write_secret("unifi/api-key", api.pop("api_key"))
            unifi["api"] = api
        runtime["unifi"] = unifi
    except Exception:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        raise

    def cleanup() -> None:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        for directory in sorted({p.parent for p in created} | {root_path}, key=lambda p: len(str(p)), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass

    atexit.register(cleanup)
    return runtime
