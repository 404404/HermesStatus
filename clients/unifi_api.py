"""Bounded, read-only UniFi Network API collector.

The API surface is deliberately fixed: configuration can select only a
file-backed key and a controller root; request paths and methods are not
caller supplied. SSH remains the source of generic host telemetry. API
responses are reduced to bounded, typed summaries before entering Device v2.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import ssl
import stat
from datetime import datetime, timezone
from http.client import HTTPSConnection
from urllib.parse import urlsplit

API_ENDPOINTS = (
    ("info", "/proxy/network/integration/v1/info"),
    ("sites", "/proxy/network/integration/v1/sites"),
    ("devices", "/proxy/network/integration/v1/devices"),
    ("clients", "/proxy/network/integration/v1/clients"),
    ("networks", "/proxy/network/integration/v1/networks"),
)
MAX_RESPONSE_BYTES = 1 << 20
MAX_KEY_BYTES = 4096
MAX_API_ITEMS = 64
MAX_API_TEXT = 128
MAX_API_TEMPERATURES = 16
MAX_API_WANS = 16
MAX_API_UPLINKS = 32


class APIError(RuntimeError):
    def __init__(self, code: str, *, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_error(code: str):
    messages = {
        "api_configuration": "UniFi API configuration is invalid",
        "api_key_file_error": "UniFi API credential file is unavailable",
        "api_auth_failure": "UniFi API authentication failed",
        "api_tls_failure": "UniFi API TLS validation failed",
        "api_transport_failure": "UniFi API transport is unavailable",
        "api_timeout": "UniFi API request timed out",
        "api_http_error": "UniFi API returned an HTTP error",
        "api_parse_failure": "UniFi API response was not valid JSON",
        "api_endpoint_unsupported": "UniFi API endpoint is unsupported",
        "api_partial_failure": "UniFi API returned a partial observation",
    }
    return {
        "code": code,
        "message": messages.get(code, "UniFi API is unavailable"),
        "source": "unifi-api",
        "retryable": code not in {"api_configuration", "api_key_file_error"},
        "http_status": None,
    }


def api_disabled():
    return {
        "enabled": False,
        "status": "disabled",
        "last_attempt": None,
        "last_success": None,
        "endpoints": [],
        "summary": None,
        "telemetry": None,
        "error": None,
    }


def _read_key(path: str) -> str:
    try:
        info = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_mode & 0o077:
            raise APIError("api_key_file_error")
        if info.st_size <= 0 or info.st_size > MAX_KEY_BYTES:
            raise APIError("api_key_file_error")
        with open(path, "rb") as handle:
            value = handle.read(MAX_KEY_BYTES + 1)
    except APIError:
        raise
    except (OSError, ValueError) as exc:
        raise APIError("api_key_file_error") from exc
    if len(value) > MAX_KEY_BYTES:
        raise APIError("api_key_file_error")
    try:
        key = value.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise APIError("api_key_file_error") from exc
    if not key or any(ch in key for ch in "\r\n"):
        raise APIError("api_key_file_error")
    return key


def _context(ca_file: str | None):
    try:
        return ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
    except (OSError, ssl.SSLError) as exc:
        raise APIError("api_tls_failure") from exc


def _text(value):
    if isinstance(value, str) and value.strip():
        return value.strip()[:MAX_API_TEXT]
    return None


def _number(value, *, integer=False, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        return None
    if integer and number.is_integer():
        return int(number)
    return number


def _boolean(value):
    return value if isinstance(value, bool) else None


def _first(mapping, *keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _items(payload):
    """Return a bounded list from common direct/data/items API shapes."""
    value = payload
    if isinstance(value, dict):
        for key in ("data", "items", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                value = candidate
                break
            if isinstance(candidate, dict) and key == "data":
                value = candidate
                break
    if isinstance(value, dict):
        for key in ("items", "results"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                value = candidate
                break
    if not isinstance(value, list):
        return []
    return [item for item in value[:MAX_API_ITEMS] if isinstance(item, dict)]


def _nested_records(mapping, *keys):
    if not isinstance(mapping, dict):
        return []
    for key in keys:
        value = mapping.get(key)
        records = _items(value)
        if records:
            return records
        if isinstance(value, dict):
            return [value]
    return []


def _summary(name: str, payload):
    if not isinstance(payload, (dict, list)):
        raise APIError("api_parse_failure")
    if name != "info":
        return None
    source = payload if isinstance(payload, dict) else {}
    result = {}
    for out, keys in (
        ("model", ("model", "model_name", "modelName", "device_model")),
        ("firmware", ("firmware", "firmware_version", "firmwareVersion", "os_version", "version")),
        ("application_version", ("application_version", "applicationVersion", "app_version", "appVersion")),
    ):
        value = _text(_first(source, *keys))
        if value:
            result[out] = value
    return result or None


def _identity(info, devices):
    source = info if isinstance(info, dict) else {}
    gateway = next(iter(devices), {})
    result = {}
    aliases = {
        "model": ("model", "model_name", "modelName", "device_model"),
        "display_name": ("display_name", "displayName", "name", "hostname"),
        "firmware": ("firmware", "firmware_version", "firmwareVersion", "os_version"),
        "status": ("status", "state", "device_status"),
    }
    for output, keys in aliases.items():
        value = _text(_first(source, *keys)) or _text(_first(gateway, *keys))
        if value:
            result[output] = value
    uptime = _number(_first(source, "uptime_seconds", "uptimeSeconds", "uptime"))
    if uptime is None:
        uptime = _number(_first(gateway, "uptime_seconds", "uptimeSeconds", "uptime"))
    if uptime is not None:
        result["uptime_seconds"] = uptime
    return result or None


def _controller(info):
    source = info if isinstance(info, dict) else {}
    result = {}
    for output, keys in (
        ("application_version", ("application_version", "applicationVersion", "app_version", "appVersion")),
        ("build", ("build", "build_number", "buildNumber")),
        ("state", ("controller_state", "controllerState", "state", "status")),
    ):
        value = _text(_first(source, *keys))
        if value:
            result[output] = value
    update = _boolean(_first(source, "update_available", "updateAvailable"))
    if update is not None:
        result["update_available"] = update
    return result or None


def _status_online(value):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"online", "connected", "adopted", "up", "active"}:
        return True
    if text in {"offline", "disconnected", "down", "inactive", "error"}:
        return False
    return None


def _device_summary(devices):
    if not devices:
        return None
    online = offline = 0
    by_type = {"gateway": 0, "ap": 0, "switch": 0, "other": 0}
    for item in devices[:MAX_API_ITEMS]:
        state = _status_online(_first(item, "online", "is_online", "status", "state"))
        if state is True:
            online += 1
        elif state is False:
            offline += 1
        kind = str(_first(item, "type", "device_type", "deviceType", "category") or "").lower()
        if "gateway" in kind or "console" in kind or "udm" in kind or "ucg" in kind:
            bucket = "gateway"
        elif "access" in kind or kind in {"ap", "access_point"}:
            bucket = "ap"
        elif "switch" in kind:
            bucket = "switch"
        else:
            bucket = "other"
        by_type[bucket] += 1
    return {"total": len(devices), "online": online, "offline": offline, "by_type": by_type}


def _client_summary(clients):
    if not clients:
        return None
    wired = wireless = 0
    wired_observed = wireless_observed = False
    for item in clients[:MAX_API_ITEMS]:
        kind = str(_first(item, "connection_type", "connectionType", "type", "medium") or "").lower()
        is_wired = _boolean(_first(item, "wired", "is_wired", "isWired"))
        if is_wired is None:
            if "wireless" in kind or "wifi" in kind or "wlan" in kind:
                is_wired = False
            elif "wired" in kind or "ethernet" in kind or "lan" in kind:
                is_wired = True
        if is_wired is True:
            wired += 1
            wired_observed = True
        elif is_wired is False:
            wireless += 1
            wireless_observed = True
    result = {"total": len(clients), "wired": wired if wired_observed else None, "wireless": wireless if wireless_observed else None, "observed": True}
    return result


def _network_summary(networks):
    if not networks:
        return None
    vlan = 0
    for item in networks[:MAX_API_ITEMS]:
        kind = str(_first(item, "type", "network_type", "purpose") or "").lower()
        if "vlan" in kind or _boolean(_first(item, "vlan_only", "vlanOnly")) is True:
            vlan += 1
    return {"total": len(networks), "vlan": vlan}


def _temperature_records(devices):
    result = []
    for device in devices:
        for sensor in _nested_records(device, "temperatures", "temperature_sensors", "sensors"):
            value = _number(_first(sensor, "celsius", "temperature_c", "temperatureC", "temp_c", "value"), minimum=-100)
            if value is None or value > 250:
                continue
            sensor_id = _text(_first(sensor, "id", "name", "sensor_id"))
            label = _text(_first(sensor, "label", "name", "type")) or sensor_id
            if not sensor_id or not label:
                continue
            result.append({"id": sensor_id, "label": label, "celsius": value, "source": "unifi-api"})
            if len(result) >= MAX_API_TEMPERATURES:
                return result
    return result


def _wan_record(item):
    if not isinstance(item, dict):
        return None
    result = {}
    for output, keys in (
        ("id", ("id", "wan_id", "wanId")),
        ("name", ("name", "display_name", "displayName")),
        ("interface", ("interface", "interface_name", "interfaceName", "ifname")),
        ("isp", ("isp", "provider", "provider_name", "providerName")),
        ("link_state", ("link_state", "linkState", "state", "status")),
        ("failover_state", ("failover_state", "failoverState")),
        ("load_balancing_state", ("load_balancing_state", "loadBalancingState")),
    ):
        value = _text(_first(item, *keys))
        if value:
            result[output] = value
    for output, keys in (
        ("online", ("online", "is_online", "isOnline")),
        ("active", ("active", "is_active", "isActive")),
        ("standby", ("standby", "is_standby", "isStandby")),
    ):
        value = _boolean(_first(item, *keys))
        if value is not None:
            result[output] = value
    for output, keys, integer in (
        ("uptime_seconds", ("uptime_seconds", "uptimeSeconds", "uptime"), False),
        ("downtime_seconds", ("downtime_seconds", "downtimeSeconds", "downtime"), False),
        ("latency_ms", ("latency_ms", "latencyMs", "latency"), False),
        ("packet_loss_percent", ("packet_loss_percent", "packetLossPercent", "packet_loss", "loss_percent"), False),
        ("rx_bps", ("rx_bps", "rxBps", "download_bps", "downloadBps"), True),
        ("tx_bps", ("tx_bps", "txBps", "upload_bps", "uploadBps"), True),
        ("rx_bytes", ("rx_bytes", "rxBytes", "download_bytes", "downloadBytes"), True),
        ("tx_bytes", ("tx_bytes", "txBytes", "upload_bytes", "uploadBytes"), True),
        ("configured_upstream_bps", ("configured_upstream_bps", "upstream_bps", "upstreamBps"), True),
        ("configured_downstream_bps", ("configured_downstream_bps", "downstream_bps", "downstreamBps"), True),
    ):
        value = _number(_first(item, *keys), integer=integer)
        if value is not None:
            result[output] = value
    if not result:
        return None
    return result


def _wans_and_uplinks(devices):
    wans, uplinks = [], []
    for device in devices:
        records = _nested_records(device, "wans", "wan", "wan_interfaces", "uplinks", "interfaces")
        expanded = [device] + list(records)
        for record in records:
            expanded.extend(_nested_records(record, "uplinks", "interfaces"))
        for item in expanded:
            name = str(_first(item, "name", "interface", "interface_name", "type") or "").lower()
            is_wan = any(token in name for token in ("wan", "internet", "pppoe")) or any(key in item for key in ("isp", "packet_loss_percent", "rx_bps", "tx_bps"))
            if is_wan and len(wans) < MAX_API_WANS:
                record = _wan_record(item)
                if record:
                    wans.append(record)
            elif len(uplinks) < MAX_API_UPLINKS:
                uplink = {}
                for output, keys in (("name", ("name", "interface", "interface_name", "interfaceName")), ("link_state", ("link_state", "linkState", "state", "status")), ("duplex", ("duplex",)), ("wan_id", ("wan_id", "wanId"))):
                    value = _text(_first(item, *keys))
                    if value:
                        uplink[output] = value
                speed = _number(_first(item, "speed_mbps", "speedMbps", "link_speed_mbps", "linkSpeedMbps"))
                if speed is not None:
                    uplink["speed_mbps"] = speed
                if uplink:
                    uplinks.append(uplink)
    return wans or None, uplinks or None


def _telemetry(payloads):
    info = payloads.get("info")
    devices = _items(payloads.get("devices"))
    clients = _items(payloads.get("clients"))
    networks = _items(payloads.get("networks"))
    identity = _identity(info, devices)
    controller = _controller(info)
    wans, uplinks = _wans_and_uplinks(devices)
    telemetry = {
        "identity": identity,
        "controller": controller,
        "wans": wans,
        "uplinks": uplinks,
        "temperatures": _temperature_records(devices) or None,
        "clients": _client_summary(clients),
        "devices": _device_summary(devices),
        "networks": _network_summary(networks),
    }
    return telemetry if any(value is not None for value in telemetry.values()) else None


def _request(config, path: str, key: str):
    parsed = urlsplit(config.base_url)
    connection = None
    response = None
    body = b""
    try:
        connection = HTTPSConnection(parsed.hostname, parsed.port or 443, context=_context(config.ca_file), timeout=config.timeout_seconds)
        connection.request("GET", path, headers={"X-API-Key": key, "Accept": "application/json"})
        response = connection.getresponse()
        cert = connection.sock.getpeercert(binary_form=True) if connection.sock else b""
        expected = getattr(config, "tls_sha256", None)
        if expected and hashlib.sha256(cert).hexdigest().lower() != expected.lower():
            raise APIError("api_tls_failure")
        body = response.read(MAX_RESPONSE_BYTES + 1)
    except APIError:
        raise
    except TimeoutError as exc:
        raise APIError("api_timeout") from exc
    except ssl.SSLError as exc:
        raise APIError("api_tls_failure") from exc
    except OSError as exc:
        raise APIError("api_transport_failure") from exc
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
    if len(body) > MAX_RESPONSE_BYTES:
        raise APIError("api_http_error")
    if response is None:
        raise APIError("api_transport_failure")
    if response.status in (401, 403):
        raise APIError("api_auth_failure", status=response.status)
    if response.status == 404:
        raise APIError("api_endpoint_unsupported", status=response.status)
    if response.status < 200 or response.status >= 300:
        raise APIError("api_http_error", status=response.status)
    content_type = response.getheader("Content-Type", "").lower()
    if content_type and "json" not in content_type:
        raise APIError("api_parse_failure", status=response.status)
    try:
        return json.loads(body.decode("utf-8")), response.status
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise APIError("api_parse_failure", status=response.status) from exc


class UniFiAPICollector:
    def __init__(self, config, *, request=None):
        self.config = config
        self._request = request or _request

    def collect(self):
        attempted = _now()
        try:
            key = _read_key(self.config.api_key_file)
        except APIError as exc:
            return {"enabled": True, "status": "unavailable", "last_attempt": attempted,
                    "last_success": None, "endpoints": [], "summary": None, "telemetry": None, "error": _safe_error(exc.code)}
        endpoint_results = []
        payloads = {}
        summary = None
        failures = []
        for name, path in API_ENDPOINTS:
            try:
                payload, status = self._request(self.config, path, key)
            except APIError as exc:
                error = _safe_error(exc.code)
                if exc.status is not None:
                    error["http_status"] = exc.status
                endpoint_results.append({"name": name, "status": "unsupported" if exc.code == "api_endpoint_unsupported" else "error", "http_status": exc.status, "error": error})
                failures.append(error)
                continue
            endpoint_results.append({"name": name, "status": "ok", "http_status": status, "error": None})
            payloads[name] = payload
            if name == "info":
                summary = _summary(name, payload)
        telemetry = _telemetry(payloads)
        if not payloads:
            error = failures[0] if failures else _safe_error("api_transport_failure")
            return {"enabled": True, "status": "unavailable", "last_attempt": attempted,
                    "last_success": None, "endpoints": endpoint_results, "summary": summary, "telemetry": telemetry, "error": error}
        if failures:
            error = _safe_error("api_partial_failure")
            status = "partial"
        else:
            error = None
            status = "available"
        return {"enabled": True, "status": status, "last_attempt": attempted,
                "last_success": attempted, "endpoints": endpoint_results, "summary": summary,
                "telemetry": telemetry, "error": error}
