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
from urllib.parse import quote, urlsplit

API_ENDPOINTS = (
    ("info", "/proxy/network/integration/v1/info"),
    ("sites", "/proxy/network/integration/v1/sites"),
)
REQUIRED_ENDPOINTS = frozenset({"info", "sites", "devices", "device_detail"})
SITE_RESOURCE_LIMIT = 32
API_ID_LIMIT = 128
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
        "api_site_ambiguity": "UniFi API site selection is ambiguous",
        "api_site_not_found": "UniFi API site selection found no match",
        "api_target_resolution": "UniFi API target device could not be resolved",
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


def _context(ca_file: str | None, tls_sha256: str | None = None):
    try:
        if ca_file:
            context = ssl.create_default_context(cafile=ca_file)
            # An explicit certificate pin is the deterministic identity check
            # for local controllers whose certificate SAN does not contain the
            # configured IP.  Keep CA validation when a CA is supplied, but
            # let the pin—not an automatic fallback—decide peer identity.
            if tls_sha256:
                context.check_hostname = False
            return context
        if tls_sha256:
            # Pin-only mode is explicit in configuration.  The peer certificate
            # is still required below and must match the exact SHA-256 pin.
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            return context
        return ssl.create_default_context()
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


def _identifier(value):
    """Accept only bounded response identifiers for path construction."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > API_ID_LIMIT:
        return None
    if any(ord(char) < 0x20 or char in "/?#" for char in value):
        return None
    return value


def _site_records(payload):
    result = []
    for item in _items(payload)[:SITE_RESOURCE_LIMIT]:
        site_id = _identifier(item.get("id"))
        if not site_id:
            continue
        record = {"id": site_id}
        for output, keys in (
            ("internal_reference", ("internalReference", "internal_reference")),
            ("name", ("name", "displayName", "display_name")),
        ):
            value = _text(_first(item, *keys))
            if value:
                record[output] = value
        result.append(record)
    return result


def _resolve_site(payload, selector=None):
    sites = _site_records(payload)
    if selector is not None:
        selector = _identifier(selector)
        if selector is None:
            raise APIError("api_site_not_found")
        matches = [
            site for site in sites
            if selector.casefold() in {
                site["id"].casefold(),
                str(site.get("internal_reference", "")).casefold(),
                str(site.get("name", "")).casefold(),
            }
        ]
        if len(matches) != 1:
            raise APIError("api_site_ambiguity" if len(matches) > 1 else "api_site_not_found")
        return matches[0]
    if len(sites) == 1:
        return sites[0]
    if not sites:
        raise APIError("api_site_not_found")
    raise APIError("api_site_ambiguity")


def _normalized_token(value):
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def _target_device(devices, profile_id=None):
    candidates = [item for item in devices[:MAX_API_ITEMS] if _identifier(item.get("id"))]
    if not candidates:
        raise APIError("api_target_resolution")
    token = _normalized_token(profile_id)
    scored = []
    for item in candidates:
        score = 0
        model = _normalized_token(_first(item, "model", "model_name", "modelName"))
        name = _normalized_token(_first(item, "name", "display_name", "displayName"))
        role = _normalized_token(_first(item, "role", "type", "device_type", "deviceType", "category"))
        if token and token in model:
            score += 8
        if token and token in name:
            score += 4
        if any(value in role for value in ("gateway", "console", "router")):
            score += 2
        if score:
            scored.append((score, item))
    if not scored:
        raise APIError("api_target_resolution")
    highest = max(score for score, _ in scored)
    matches = [item for score, item in scored if score == highest]
    if len(matches) != 1:
        raise APIError("api_target_resolution")
    return matches[0]


def _site_path(site_id, resource, device_id=None, suffix=None):
    parts = ["/proxy/network/integration/v1/sites", quote(site_id, safe=""), resource]
    if device_id is not None:
        parts.append(quote(device_id, safe=""))
    if suffix:
        parts.append(suffix)
    return "/".join(parts)


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


def _identity(info, devices, target=None):
    source = info if isinstance(info, dict) else {}
    gateway = target if isinstance(target, dict) else next(iter(devices), {})
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


def _controller(info, target=None):
    source = info if isinstance(info, dict) else {}
    detail = target if isinstance(target, dict) else {}
    result = {}
    for output, keys in (
        ("application_version", ("application_version", "applicationVersion", "app_version", "appVersion")),
        ("build", ("build", "build_number", "buildNumber")),
        ("state", ("controller_state", "controllerState", "state", "status")),
    ):
        value = _text(_first(source, *keys)) or _text(_first(detail, *keys))
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
        if "vlan" in kind or _boolean(_first(item, "vlan_only", "vlanOnly")) is True or _first(item, "vlan_id", "vlanId") is not None:
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


def _latest_statistics(stats):
    if not isinstance(stats, dict):
        return None
    result = {}
    for output, keys, minimum, maximum in (
        ("cpu_utilization_pct", ("cpuUtilizationPct", "cpu_utilization_pct"), 0, 100),
        ("memory_utilization_pct", ("memoryUtilizationPct", "memory_utilization_pct"), 0, 100),
        ("load_average_1m", ("loadAverage1Min", "load_average_1m"), 0, None),
        ("load_average_5m", ("loadAverage5Min", "load_average_5m"), 0, None),
        ("load_average_15m", ("loadAverage15Min", "load_average_15m"), 0, None),
        ("uptime_seconds", ("uptimeSec", "uptime_seconds"), 0, None),
    ):
        value = _number(_first(stats, *keys), minimum=minimum)
        if value is not None and (maximum is None or value <= maximum):
            result[output] = value
    heartbeat = _text(_first(stats, "lastHeartbeatAt", "last_heartbeat_at"))
    if heartbeat:
        result["last_heartbeat_at"] = heartbeat
    uplink = stats.get("uplink")
    if isinstance(uplink, dict):
        rates = {}
        for output, keys in (("rx_bps", ("rxRateBps", "rx_bps")), ("tx_bps", ("txRateBps", "tx_bps"))):
            value = _number(_first(uplink, *keys), integer=True)
            if value is not None:
                rates[output] = value
        if rates:
            result["uplink"] = rates
    return result or None


def _telemetry(payloads, *, site=None, target=None):
    info = payloads.get("info")
    devices = _items(payloads.get("devices"))
    clients = _items(payloads.get("clients"))
    networks = _items(payloads.get("networks"))
    target_detail = payloads.get("device_detail")
    target_stats = payloads.get("device_stats")
    identity = _identity(info, devices, target_detail or target)
    controller = _controller(info, target_detail or target)
    wans, uplinks = _wans_and_uplinks(devices)
    statistics = _latest_statistics(target_stats)
    if statistics and statistics.get("uplink"):
        uplinks = (uplinks or [])[:MAX_API_UPLINKS]
        uplinks.append({"name": "uplink", **statistics["uplink"]})
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
        expected = getattr(config, "tls_sha256", None)
        connection = HTTPSConnection(parsed.hostname, parsed.port or 443, context=_context(config.ca_file, expected), timeout=config.timeout_seconds)
        connection.request("GET", path, headers={"X-API-Key": key, "Accept": "application/json"})
        response = connection.getresponse()
        cert = connection.sock.getpeercert(binary_form=True) if connection.sock else b""
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
    def __init__(self, config, *, request=None, target_profile=None):
        self.config = config
        self._request = request or _request
        self.target_profile = target_profile or getattr(config, "profile_id", None)
        self.site_selector = getattr(config, "site_id", None)

    def collect(self):
        attempted = _now()
        try:
            key = _read_key(self.config.api_key_file)
        except APIError as exc:
            return {"enabled": True, "status": "unavailable", "last_attempt": attempted,
                    "last_success": None, "endpoints": [], "summary": None,
                    "telemetry": None, "error": _safe_error(exc.code)}
        endpoint_results = []
        payloads = {}
        failures = []
        failure_details = {}

        def call(name, path, *, required, report=True):
            try:
                payload, status = self._request(self.config, path, key)
            except APIError as exc:
                error = _safe_error(exc.code)
                if exc.status is not None:
                    error["http_status"] = exc.status
                failure_details[name] = error
                if report:
                    endpoint_results.append({
                        "name": name,
                        "status": "unsupported" if exc.code == "api_endpoint_unsupported" else "error",
                        "http_status": exc.status,
                        "error": error,
                    })
                failures.append((name, error, required))
                return None
            if report:
                endpoint_results.append({"name": name, "status": "ok", "http_status": status, "error": None})
            payloads[name] = payload
            return payload

        for name, path in API_ENDPOINTS:
            call(name, path, required=True)

        selected_site = None
        target = None
        sites = payloads.get("sites")
        if sites is not None:
            try:
                selected_site = _resolve_site(sites, self.site_selector)
            except APIError as exc:
                error = _safe_error(exc.code)
                failure_details["sites"] = error
                for item in endpoint_results:
                    if item["name"] == "sites":
                        item.update({"status": "error", "http_status": None, "error": error})
                        break
                failures.append(("sites", error, True))
        if selected_site is not None:
            site_id = selected_site["id"]
            devices = call("devices", _site_path(site_id, "devices"), required=True)
            device_records = _items(devices)
            if devices is not None:
                try:
                    target = _target_device(device_records, self.target_profile)
                except APIError as exc:
                    error = _safe_error(exc.code)
                    failure_details["devices"] = error
                    for item in endpoint_results:
                        if item["name"] == "devices":
                            item.update({"status": "error", "http_status": None, "error": error})
                            break
                    failures.append(("devices", error, True))
                if target is not None:
                    device_id = _identifier(target.get("id"))
                    detail = call("device_detail", _site_path(site_id, "devices", device_id), required=True, report=False)
                    stats = call("device_stats", _site_path(site_id, "devices", device_id, "statistics/latest"), required=True, report=False)
                    if detail is None or stats is None:
                        error = failure_details.get("device_detail") or failure_details.get("device_stats") or _safe_error("api_target_resolution")
                        for item in endpoint_results:
                            if item["name"] == "devices":
                                item.update({"status": "error", "http_status": error.get("http_status"), "error": error})
                                break
                        failures.append(("devices", error, True))
                    call("clients", _site_path(site_id, "clients"), required=False)
                    call("networks", _site_path(site_id, "networks"), required=False)

        summary = _summary("info", payloads.get("info")) if "info" in payloads else None
        telemetry = _telemetry(payloads, site=selected_site, target=target)
        successful_count = sum(1 for item in endpoint_results if item["status"] == "ok")
        failed_count = sum(1 for item in endpoint_results if item["status"] != "ok")
        required_failures = [error for _, error, required in failures if required]
        if required_failures and successful_count and failed_count:
            error = _safe_error("api_partial_failure")
            status = "partial"
            last_success = attempted if successful_count else None
        elif required_failures:
            error = required_failures[0]
            status = "unavailable"
            last_success = None
        elif failed_count:
            error = _safe_error("api_partial_failure")
            status = "partial"
            last_success = attempted
        else:
            error = None
            status = "available"
            last_success = attempted
        return {
            "enabled": True,
            "status": status,
            "last_attempt": attempted,
            "last_success": last_success,
            "endpoints": endpoint_results,
            "summary": summary,
            "telemetry": telemetry,
            "error": error,
        }
