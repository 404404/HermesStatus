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
import time
from datetime import datetime, timezone
from http.client import HTTPSConnection
from urllib.parse import quote, urlsplit

API_ENDPOINTS = (
    ("info", "/proxy/network/integration/v1/info"),
    ("sites", "/proxy/network/integration/v1/sites"),
)
WAN_ENDPOINTS = (
    ("wan_official", "official"),
    ("wan_enriched", "supplemental_v2"),
    ("wan_isp_status", "supplemental_v2"),
    ("wan_load_balance", "supplemental_v2"),
    ("wan_slas", "supplemental_v2"),
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
MAX_API_PORTS = 64
MAX_API_LAGS = 16
MAX_API_TOPOLOGY_LINKS = 32
MAX_API_ANOMALIES = 16


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


def _decimal(value, *, minimum=0):
    parsed = _number(value, minimum=minimum)
    if parsed is not None:
        return parsed
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        if math.isfinite(number) and number >= minimum:
            return number
    return None


def _counter(mapping, *keys):
    value = _first(mapping, *keys)
    parsed = _number(value, integer=True)
    if parsed is not None:
        return parsed
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        if math.isfinite(number) and number >= 0 and number.is_integer():
            return int(number)
    return None


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
    # Official responses and statistics may nest link/health/traffic fields
    # one level below the WAN record. Flatten only reviewed object keys so the
    # projection remains bounded and typed; arbitrary payload keys are never
    # emitted.
    source = dict(item)
    for nested_name in ("link", "status", "health", "metrics", "statistics", "performance", "uplink"):
        nested = item.get(nested_name)
        if isinstance(nested, dict):
            for key, value in nested.items():
                source.setdefault(key, value)
    result = {}
    for output, keys in (
        ("id", ("id", "wan_id", "wanId", "interface_id", "interfaceId")),
        ("name", ("name", "display_name", "displayName", "label")),
        ("interface", ("interface", "interface_name", "interfaceName", "ifname", "interface_id", "interfaceId")),
        ("isp", ("isp", "provider", "provider_name", "providerName", "carrier", "vendor")),
        ("link_state", ("link_state", "linkState", "link_status", "linkStatus", "state", "status", "connection_state", "connectionState")),
        ("gateway", ("gateway", "gateway_name", "gatewayName", "gateway_address", "gatewayAddress")),
        ("sla_status", ("sla_status", "slaStatus", "health", "health_status", "healthStatus")),
        ("failover_state", ("failover_state", "failoverState")),
        ("load_balancing_state", ("load_balancing_state", "loadBalancingState")),
    ):
        value = _text(_first(source, *keys))
        if value:
            result[output] = value
    for output, keys in (
        ("online", ("online", "is_online", "isOnline", "connected")),
        ("active", ("active", "is_active", "isActive")),
        ("standby", ("standby", "is_standby", "isStandby")),
    ):
        value = _boolean(_first(source, *keys))
        if value is not None:
            result[output] = value
    for output, keys, integer in (
        ("uptime_seconds", ("uptime_seconds", "uptimeSeconds", "uptime"), False),
        ("downtime_seconds", ("downtime_seconds", "downtimeSeconds", "downtime"), False),
        ("latency_ms", ("latency_ms", "latencyMs", "latency", "round_trip_ms", "roundTripMs"), False),
        ("packet_loss_percent", ("packet_loss_percent", "packetLossPercent", "packet_loss", "loss_percent", "lossPercent"), False),
        ("jitter_ms", ("jitter_ms", "jitterMs", "jitter"), False),
        ("link_speed_mbps", ("link_speed_mbps", "linkSpeedMbps", "speed_mbps", "speedMbps", "speed"), False),
        ("rx_bps", ("rx_bps", "rxBps", "download_bps", "downloadBps", "rx_rate_bps", "rxRateBps"), True),
        ("tx_bps", ("tx_bps", "txBps", "upload_bps", "uploadBps", "tx_rate_bps", "txRateBps"), True),
        ("rx_bytes", ("rx_bytes", "rxBytes", "download_bytes", "downloadBytes"), True),
        ("tx_bytes", ("tx_bytes", "txBytes", "upload_bytes", "uploadBytes"), True),
        ("configured_upstream_bps", ("configured_upstream_bps", "upstream_bps", "upstreamBps"), True),
        ("configured_downstream_bps", ("configured_downstream_bps", "downstream_bps", "downstreamBps"), True),
    ):
        value = _number(_first(source, *keys), integer=integer)
        if value is not None:
            result[output] = value
    if not result:
        return None
    return result


def _statistics_wans(payload):
    """Extract only explicitly WAN-named records from latest statistics."""
    if not isinstance(payload, dict):
        return []
    records = []
    for key in ("wans", "wan", "wan_interfaces", "wanInterfaces", "wan_status", "wanStatus"):
        value = payload.get(key)
        if isinstance(value, list):
            records.extend(item for item in value[:MAX_API_WANS] if isinstance(item, dict))
        elif isinstance(value, dict):
            records.append(value)
    return records[:MAX_API_WANS]


def _wan_items(payload):
    if isinstance(payload, dict):
        direct = _wan_record(payload)
        if direct:
            return [payload]
        for key in ("wans", "wan", "interfaces", "items", "results", "data"):
            value = payload.get(key)
            if isinstance(value, dict):
                nested = _wan_items(value)
                if nested:
                    return nested
            elif isinstance(value, list):
                return [item for item in value[:MAX_API_WANS] if isinstance(item, dict)]
    return [item for item in _items(payload)[:MAX_API_WANS] if isinstance(item, dict)]


def _merge_wans(*payloads):
    merged = {}
    for payload in payloads:
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            items = _wan_items(candidate)
            for item in items:
                record = _wan_record(item)
                if not record:
                    continue
                key = record.get("id") or record.get("interface") or record.get("name")
                if not key:
                    continue
                current = merged.setdefault(key, {})
                current.update(record)
    return list(merged.values())[:MAX_API_WANS] or None


def _detail_link_speed(target_detail):
    """Return the highest observed target port speed, if the API exposes it."""
    if not isinstance(target_detail, dict):
        return None
    interfaces = target_detail.get("interfaces")
    ports = interfaces.get("ports") if isinstance(interfaces, dict) else None
    if not isinstance(ports, list):
        return None
    observed = []
    advertised = []
    for port in ports[:MAX_API_UPLINKS]:
        if not isinstance(port, dict):
            continue
        state = str(_first(port, "state", "status", "linkState") or "").strip().lower()
        speed = _number(_first(port, "speedMbps", "speed_mbps", "linkSpeedMbps"), minimum=0)
        maximum = _number(_first(port, "maxSpeedMbps", "max_speed_mbps"), minimum=0)
        if speed is not None and state not in {"down", "offline", "disconnected", "disabled"}:
            observed.append(speed)
        if maximum is not None:
            advertised.append(maximum)
    values = observed or advertised
    return max(values) if values else None


def _wans_and_uplinks(devices, target_detail=None, extra_wans=None):
    wans, uplinks = [], []
    target_id = _identifier(target_detail.get("id")) if isinstance(target_detail, dict) else None
    target_speed = _detail_link_speed(target_detail)
    for device in devices:
        source_device = device
        if target_id and _identifier(device.get("id")) == target_id and target_speed is not None:
            source_device = dict(device)
            source_device["speed_mbps"] = target_speed
        records = _nested_records(device, "wans", "wan", "wan_interfaces", "uplinks", "interfaces")
        expanded = [source_device] + list(records)
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
                for output, keys in (("name", ("model", "model_name", "modelName", "device_model", "name", "interface", "interface_name", "interfaceName")), ("link_state", ("link_state", "linkState", "state", "status")), ("duplex", ("duplex",)), ("wan_id", ("wan_id", "wanId"))):
                    value = _text(_first(item, *keys))
                    if value:
                        uplink[output] = value
                speed = _number(_first(item, "speed_mbps", "speedMbps", "link_speed_mbps", "linkSpeedMbps"))
                if speed is not None:
                    uplink["speed_mbps"] = speed
                if uplink:
                    uplinks.append(uplink)
    return (_merge_wans(wans, extra_wans) if extra_wans else (wans or None)), uplinks or None


def _legacy_target(payload, target):
    """Select the legacy device only by the already-qualified device id."""
    target_id = _identifier(target.get("id")) if isinstance(target, dict) else None
    if not target_id:
        return None
    records = _items(payload.get("data") if isinstance(payload, dict) else payload)
    for item in records:
        # Legacy records use either device_id, _id, or external_id for the
        # same controller identity. Accept only an exact match to the
        # already-qualified official target ID; never fall back to names/MACs.
        if any(_identifier(item.get(key)) == target_id for key in ("device_id", "_id", "external_id")):
            return item
    return None


def _poe_record(port, *, max_power_w=None):
    supported = _boolean(_first(port, "port_poe"))
    if supported is None:
        caps = _counter(port, "poe_caps")
        if caps is not None:
            supported = caps > 0
    if supported is None and not any(key in port for key in ("poe_enable", "poe_power", "poe_mode", "poe_class")):
        return None
    result = {"supported": supported}
    for output, keys in (("enabled", ("poe_enable", "poe_enabled")), ("good", ("poe_good", "poeGood"))):
        value = _boolean(_first(port, *keys))
        if value is not None:
            result[output] = value
    power = _decimal(_first(port, "poe_power", "power_w", "powerW"), minimum=0)
    if power is not None and supported is not False:
        result["power_w"] = power
        result["active"] = power > 0
    if max_power_w is None:
        max_power_w = _decimal(_first(port, "poe_max_power", "poe_max_power_w", "poe_max_watts", "max_power_w", "maxPowerW"), minimum=0)
    if max_power_w is not None and supported is not False:
        result["max_power_w"] = max_power_w
    for output, keys in (("state", ("poe_state",)), ("mode", ("poe_mode",)), ("class", ("poe_class", "poe_standard"))):
        value = _text(_first(port, *keys))
        if value:
            result[output] = value
    for output, keys in (("voltage_v", ("poe_voltage", "voltage_v")), ("current_ma", ("poe_current", "current_ma"))):
        value = _decimal(_first(port, *keys), minimum=0)
        if value is not None:
            result[output] = value
    return result


def _port_record(port, *, device_id, previous_samples, sample_time, max_speed_mbps=None, max_power_w=None):
    if not isinstance(port, dict):
        return None
    index = _counter(port, "port_idx", "idx", "portIndex")
    if index is None or index < 1 or index > 65535:
        return None
    result = {"device_id": device_id, "port_idx": index}
    for output, keys in (
        ("name", ("name", "display_name", "displayName", "ifname")),
        ("media", ("media", "connector", "type")),
        ("duplex", ("full_duplex", "fullDuplex")),
        ("autoneg", ("autoneg", "auto_negotiation")),
        ("enabled", ("enable", "enabled")),
        ("up", ("up", "link_up", "is_up")),
        ("uplink", ("is_uplink", "uplink")),
    ):
        value = _first(port, *keys)
        if output in {"duplex", "autoneg", "enabled", "up", "uplink"}:
            value = _boolean(value)
        else:
            value = _text(value)
        if value is not None:
            result[output] = value
    speed = _decimal(_first(port, "speed", "speedMbps", "speed_mbps", "linkSpeedMbps"), minimum=0)
    if speed is not None:
        result["speed_mbps"] = speed
    maximum = _decimal(_first(port, "max_speed", "maxSpeed", "max_speed_mbps", "maxSpeedMbps"), minimum=0)
    if maximum is None:
        maximum = max_speed_mbps
    if maximum is not None:
        result["max_speed_mbps"] = maximum
    counter_keys = {
        "rx_bytes": ("rx_bytes", "rxBytes"), "tx_bytes": ("tx_bytes", "txBytes"),
        "rx_packets": ("rx_packets", "rxPackets"), "tx_packets": ("tx_packets", "txPackets"),
        "rx_errors": ("rx_errors", "rxErrors"), "tx_errors": ("tx_errors", "txErrors"),
        "rx_dropped": ("rx_dropped", "rxDropped"), "tx_dropped": ("tx_dropped", "txDropped"),
        "rx_multicast": ("rx_multicast", "rxMulticast"), "tx_multicast": ("tx_multicast", "txMulticast"),
        "rx_broadcast": ("rx_broadcast", "rxBroadcast"), "tx_broadcast": ("tx_broadcast", "txBroadcast"),
    }
    counters = {}
    for output, keys in counter_keys.items():
        value = _counter(port, *keys)
        if value is not None:
            counters[output] = value
    result.update(counters)
    sample_key = (device_id, index)
    previous = previous_samples.get(sample_key)
    current_sample = {"time": sample_time, "speed_mbps": result.get("speed_mbps"), "up": result.get("up"), **{key: counters[key] for key in ("rx_bytes", "tx_bytes") if key in counters}}
    if previous and current_sample.get("up") is True and all(key in previous and key in current_sample for key in ("rx_bytes", "tx_bytes")):
        elapsed = sample_time - previous["time"]
        same_speed = previous.get("speed_mbps") == current_sample.get("speed_mbps")
        same_link = previous.get("up") == current_sample.get("up")
        if 0 < elapsed <= 3600 and same_speed and same_link:
            deltas = {key: current_sample[key] - previous[key] for key in ("rx_bytes", "tx_bytes")}
            max_bps = (current_sample.get("speed_mbps") or 0) * 1_000_000 * 2
            rates = {}
            for key, delta in deltas.items():
                if delta < 0:
                    continue
                rate_key = key.replace("_bytes", "_bps")
                rate = int(round(delta / elapsed))
                # Validate each direction independently so one corrupt/reset
                # counter cannot hide a valid observation in the other.
                if max_bps and rate > max_bps:
                    continue
                rates[rate_key] = rate
            if rates:
                result.update(rates)
                speed = current_sample.get("speed_mbps")
                if speed:
                    for rate_key, utilization_key in (("rx_bps", "rx_utilization_pct"), ("tx_bps", "tx_utilization_pct")):
                        if rate_key in rates:
                            result[utilization_key] = round(rates[rate_key] * 8 / (speed * 1_000_000) * 100, 2)
    previous_samples[sample_key] = current_sample
    poe = _poe_record(port, max_power_w=max_power_w)
    if poe is not None:
        result["poe"] = poe
    connection = port.get("last_connection")
    if isinstance(connection, dict) and connection.get("connected") is True:
        result["peer_count"] = 1
    return result


def _detail_port_capabilities(target_detail):
    """Return fixed port-index capabilities from the official detail payload."""
    if not isinstance(target_detail, dict):
        return {}
    interfaces = target_detail.get("interfaces")
    ports = interfaces.get("ports") if isinstance(interfaces, dict) else None
    if not isinstance(ports, list):
        return {}
    result = {}
    for port in ports[:MAX_API_PORTS]:
        if not isinstance(port, dict):
            continue
        index = _counter(port, "port_idx", "idx", "portIndex")
        if index is None or index < 1 or index > 65535:
            continue
        maximum = _decimal(_first(port, "maxSpeedMbps", "max_speed_mbps", "max_speed"), minimum=0)
        max_power = None
        poe = _first(port, "poe", "powerOverEthernet")
        if isinstance(poe, dict):
            max_power = _decimal(_first(poe, "maxPowerW", "max_power_w", "maxPower", "powerLimitW"), minimum=0)
        result[index] = {"max_speed_mbps": maximum, "max_power_w": max_power}
    return result


def _device_poe_totals(target_detail):
    if not isinstance(target_detail, dict):
        return None, None
    current = _decimal(_first(target_detail, "poe_total_power_w", "poeTotalPowerW", "total_poe_power_w", "totalPoePowerW"), minimum=0)
    maximum = _decimal(_first(target_detail, "poe_max_power_w", "poeMaxPowerW", "total_max_power_w", "totalMaxPowerW", "poe_budget_w", "poeBudgetW"), minimum=0)
    poe = _first(target_detail, "poe", "power_over_ethernet", "powerOverEthernet")
    if isinstance(poe, dict):
        if current is None:
            current = _decimal(_first(poe, "total_power_w", "totalPowerW", "power_w", "powerW"), minimum=0)
        if maximum is None:
            maximum = _decimal(_first(poe, "max_power_w", "maxPowerW", "budget_w", "budgetW"), minimum=0)
    return current, maximum


def _ports(legacy_payload, target, previous_samples, sample_time, target_detail=None):
    legacy = _legacy_target(legacy_payload, target)
    if legacy is None:
        return None, None
    device_id = _identifier(target.get("id"))
    capabilities = _detail_port_capabilities(target_detail)
    records = []
    for port in (legacy.get("port_table") or [])[:MAX_API_PORTS]:
        index = _counter(port, "port_idx", "idx", "portIndex")
        detail = capabilities.get(index, {})
        item = _port_record(port, device_id=device_id, previous_samples=previous_samples, sample_time=sample_time,
                            max_speed_mbps=detail.get("max_speed_mbps"), max_power_w=detail.get("max_power_w"))
        if item is not None:
            records.append(item)
    summary = {"total": len(records), "up": sum(1 for item in records if item.get("up") is True), "down": sum(1 for item in records if item.get("up") is False), "poe_active": 0, "poe_total_power_w": None, "poe_total_source": "unavailable", "poe_max_power_w": None}
    poe_items = [item.get("poe", {}) for item in records if isinstance(item.get("poe"), dict)]
    summary["poe_active"] = sum(1 for item in poe_items if item.get("active") is True)
    powers = [item.get("power_w") for item in poe_items if isinstance(item.get("power_w"), (int, float))]
    device_current, device_max = _device_poe_totals(target_detail)
    if device_current is not None:
        summary["poe_total_power_w"] = round(device_current, 2)
        summary["poe_total_source"] = "device_reported"
    elif powers:
        summary["poe_total_power_w"] = round(sum(powers), 2)
        summary["poe_total_source"] = "port_sum"
    if device_max is not None:
        summary["poe_max_power_w"] = round(device_max, 2)
    return records, summary


def _lag_records(payload):
    records = []
    for item in _items(payload)[:MAX_API_LAGS]:
        lag_id = _text(_first(item, "lag_id", "lagId", "id"))
        members = _first(item, "lag_member", "lagMember", "members", "ports")
        if isinstance(members, list):
            for member in members[:MAX_API_PORTS]:
                value = _text(member if isinstance(member, str) else _first(member, "id", "port_idx", "portIdx", "name"))
                if lag_id and value:
                    records.append({"lag_id": lag_id, "lag_member": value})
    return records


def _topology_summary(payload):
    links = []
    for item in _items(payload)[:MAX_API_TOPOLOGY_LINKS]:
        source = _identifier(_first(item, "sourceDeviceId", "source_device_id", "source"))
        target = _identifier(_first(item, "targetDeviceId", "target_device_id", "target"))
        state = _text(_first(item, "state", "status", "linkState"))
        if source or target or state:
            record = {}
            if source: record["source_device_id"] = source
            if target: record["target_device_id"] = target
            if state: record["state"] = state
            links.append(record)
    return {"link_count": len(links), "links": links}


def _anomaly_summary(payload):
    items = _items(payload)
    affected = set()
    recent = []
    for item in items[:MAX_API_ANOMALIES]:
        port = _text(_first(item, "port", "port_name", "portName", "port_idx", "portIdx"))
        kind = _text(_first(item, "type", "category", "severity"))
        if port: affected.add(port)
        if kind and len(recent) < 4: recent.append(kind)
    return {"anomaly_count": len(items), "affected_port_count": len(affected), "recent_types": recent}


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


def _telemetry(payloads, *, site=None, target=None, previous_samples=None, sample_time=None):
    info = payloads.get("info")
    devices = _items(payloads.get("devices"))
    clients = _items(payloads.get("clients"))
    networks = _items(payloads.get("networks"))
    target_detail = payloads.get("device_detail")
    # Latest statistics are required for target qualification, but the
    # current Device v2 API contract does not expose the raw statistics
    # object. Keep it out of the normalized projection unless each field is
    # explicitly represented by the server model.
    identity = _identity(info, devices, target_detail or target)
    controller = _controller(info, target_detail or target)
    extra_wans = [payloads.get(name) for name, _ in WAN_ENDPOINTS if payloads.get(name) is not None]
    extra_wans.append(_statistics_wans(payloads.get("device_stats")))
    wans, uplinks = _wans_and_uplinks(devices, target_detail, extra_wans)
    ports, port_summary = _ports(payloads.get("legacy_stat_device"), target, previous_samples if previous_samples is not None else {}, sample_time if sample_time is not None else time.monotonic(), target_detail=target_detail) if target is not None and payloads.get("legacy_stat_device") is not None else (None, None)
    telemetry = {
        "identity": identity,
        "controller": controller,
        "wans": wans,
        "uplinks": uplinks,
        "temperatures": _temperature_records(devices) or None,
        "clients": _client_summary(clients),
        "devices": _device_summary(devices),
        "networks": _network_summary(networks),
        "ports": ports,
        "port_summary": port_summary,
        "lags": _lag_records(payloads["lags"]) if payloads.get("lags") is not None else None,
        "topology": _topology_summary(payloads["topology"]) if payloads.get("topology") is not None else None,
        "anomalies": _anomaly_summary(payloads["port_anomalies"]) if payloads.get("port_anomalies") is not None else None,
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
        self._port_samples = {}

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
                    internal_reference = _identifier(selected_site.get("internal_reference"))
                    if internal_reference:
                        call("legacy_stat_device", f"/proxy/network/api/s/{quote(internal_reference, safe='')}/stat/device", required=False)
                    call("lags", _site_path(site_id, "switching/lags"), required=False)
                    call("topology", f"/proxy/network/v2/api/site/{quote(site_id, safe='')}/topology", required=False)
                    call("port_anomalies", f"/proxy/network/v2/api/site/{quote(site_id, safe='')}/ports/port-anomalies", required=False)
                    internal_site = quote(site_id, safe="")
                    network_group = quote(str(selected_site.get("internal_reference") or site_id), safe="")
                    call("wan_official", f"/proxy/network/integration/v1/sites/{internal_site}/wans", required=False)
                    call("wan_enriched", f"/proxy/network/v2/api/site/{internal_site}/wan/enriched-configuration", required=False)
                    call("wan_isp_status", f"/proxy/network/v2/api/site/{internal_site}/wan/{network_group}/isp-status", required=False)
                    call("wan_load_balance", f"/proxy/network/v2/api/site/{internal_site}/wan/load-balancing/status", required=False)
                    call("wan_slas", f"/proxy/network/v2/api/site/{internal_site}/wan-slas", required=False)

        summary = _summary("info", payloads.get("info")) if "info" in payloads else None
        telemetry = _telemetry(payloads, site=selected_site, target=target, previous_samples=self._port_samples, sample_time=time.monotonic())
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
