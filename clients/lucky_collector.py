#!/usr/bin/env python3
"""Read-only Lucky adapter for the HermesStatus extension payload."""

import datetime
import hashlib
import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

from secure_file import SecureFileError, secure_read_bounded_regular_file


MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ITEMS = 256
MAX_TEXT = 256
MAX_NAME = 128
ALLOWED_SOURCES = {"api", "local_api", "config", "cli", "web_fallback", "unavailable"}
DEFAULT_LUCKY_BASE_URL = "https://127.0.0.1:16601"
LUCKY_AUTH_MODES = {"none", "open_token", "admin_token"}
LUCKY_PROCESS_NAMES = {"lucky", "lucky_process"}

_SECRET_PATTERN = re.compile(
    r"(?i)(authorization\s*:|bearer\s+\S+|api[_-]?key\s*[:=]|password\s*[:=]|"
    r"cookie\s*[:=]|private[_-]?key\s*[:=]|openToken\s*[:=])"
)


def _timestamp(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    return now.astimezone(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_text(value, limit=MAX_TEXT, default=None):
    if value is None:
        return default
    text = " ".join(str(value).split())
    if not text:
        return default
    if _SECRET_PATTERN.search(text):
        return "[redacted]"
    return text[:limit]


def _safe_int(value, default=None, minimum=0, maximum=9007199254740991):
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < minimum or number > maximum:
        return default
    return number


def _bounded_config_int(value, default, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(number, maximum))


def _safe_bool(value, default=None):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "yes", "on", "enabled", "enable", "running", "ok"):
            return True
        if normalized in ("false", "no", "off", "disabled", "disable", "stopped"):
            return False
    return default


def _error(code, message, source="lucky", retryable=False, http_status=None):
    return {
        "code": _safe_text(code, 64, "internal_error"),
        "message": _safe_text(message, 256, "Lucky data is unavailable"),
        "source": _safe_text(source, 64, "lucky"),
        "retryable": bool(retryable),
        "http_status": http_status if isinstance(http_status, int) and 100 <= http_status <= 599 else None,
    }


def _empty_module(status="unknown", error=None):
    return {"status": status, "stale": True, "updated_at": None, "error": error}


def not_configured_lucky():
    error = _error("not_configured", "Lucky monitoring is not configured", "lucky")
    return {
        "status": "not_configured",
        "source": "unavailable",
        "service": {
            "state": "unknown", "process_running": None, "process_pid": None,
            "uptime_seconds": None, "api_reachable": False, "web_reachable": False,
            "error": error,
        },
        "version": {
            "current": None, "latest": None, "update_available": None,
            "build_info": None, "checked_at": None, "stale": True, "error": error,
        },
        "ip_resolution": {
            "mode": None, "resolved_ip_count": 0, "ipv4_count": 0, "ipv6_count": 0,
            **_empty_module("not_configured", error),
        },
        "dynamic_dns": _empty_collection("records", "not_configured", error),
        "web_services": _empty_collection("services", "not_configured", error),
        "port_forwards": _empty_collection("rules", "not_configured", error),
        "certificates": _empty_certificates("not_configured", error),
        "updated_at": None,
        "stale": True,
        "error": error,
    }


def unavailable_lucky(code="connection_refused", http_status=None,
                      process_running=None, process_pid=None):
    result = not_configured_lucky()
    error = _error(code, _error_message(code), "lucky", True, http_status)
    result.update({"status": "unavailable", "source": "local_api", "error": error})
    result["service"].update({
        "state": "running" if process_running is True else "stopped" if process_running is False else "unknown",
        "process_running": process_running,
        "process_pid": process_pid,
        "api_reachable": False,
        "web_reachable": False,
        "error": error,
    })
    for name in ("version", "ip_resolution", "dynamic_dns", "web_services", "port_forwards", "certificates"):
        # Version has no collection-status field in the strict Device v2
        # contract.  Do not manufacture one while marking an API outage, or
        # the Server will safely reject the entire Lucky projection.
        if "status" in result[name]:
            result[name]["status"] = "unavailable"
        result[name]["error"] = error
    return result


def lucky_process_state(proc_root="/proc"):
    """Return the Lucky process state without collecting command lines.

    The local API may fail while its SPK process remains running.  Inspect only
    bounded `/proc/<pid>/comm` names so no arguments, environment variables,
    credentials, or package configuration can enter the extension payload.
    """
    try:
        entries = sorted(os.listdir(proc_root))[:65536]
    except OSError:
        return None, None
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc_root, entry, "comm"), "r", encoding="utf-8", errors="replace") as handle:
                process_name = handle.read(129).strip().lower()
        except OSError:
            continue
        if process_name in LUCKY_PROCESS_NAMES:
            return True, int(entry)
    return False, None


def _empty_collection(key, status="unknown", error=None):
    return {
        "total": 0, "enabled": 0, "disabled": 0, "healthy": 0, "error_count": 0,
        key: [], "status": status, "stale": True, "updated_at": None, "error": error,
    }


def _empty_certificates(status="unknown", error=None):
    return {
        "total": 0, "valid": 0, "expiring": 0, "expired": 0,
        "not_yet_valid": 0, "invalid": 0, "unknown": 0, "items": [],
        "status": status, "stale": True, "updated_at": None, "error": error,
    }


def _error_message(code):
    return {
        "timeout": "Lucky API request timed out",
        "unauthorized": "Lucky API authentication failed",
        "forbidden": "Lucky API access was denied",
        "not_found": "Lucky API endpoint is unavailable",
        "invalid_response": "Lucky API returned an invalid response",
        "response_too_large": "Lucky API response exceeded the size limit",
        "schema_mismatch": "Lucky API response format is unsupported",
        "connection_refused": "Lucky service is unavailable",
        "invalid_configuration": "Lucky monitoring configuration is invalid",
    }.get(code, "Lucky data is unavailable")


class LuckyAPIError(Exception):
    def __init__(self, code, http_status=None):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LuckyAPIError("invalid_response", code)


class LuckyClient(object):
    """Fixed allowlist of Lucky GET endpoints; no arbitrary or write request API."""

    PATHS = {
        "version": "/version",
        "info": "/api/info",
        "status": "/api/status",
        "interfaces": "/api/netinterfaces",
        "ddns": "/api/ddnstasklist",
        "web": "/api/webservice/rules",
        "web_lite": "/api/webservice/rules_lite",
        "forward": "/api/portforwards",
        "ssl": "/api/ssl",
    }

    def __init__(self, base_url, auth_mode="open_token", token_file=None, timeout=5,
                 verify_tls=True, request_func=None):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Lucky base URL must use loopback HTTP or HTTPS")
        self.base_url = base_url.rstrip("/")
        self.auth_mode = str(auth_mode or "none").strip().lower()
        if self.auth_mode not in LUCKY_AUTH_MODES:
            raise ValueError("Lucky authentication mode is invalid")
        self.token_file = token_file
        self.timeout = max(1, min(int(timeout), 30))
        self.verify_tls = bool(verify_tls)
        self.request_func = request_func

    def _token(self):
        if not self.token_file:
            return None
        try:
            data = secure_read_bounded_regular_file(self.token_file, 4096)
            return data.decode("utf-8", errors="replace").strip() or None
        except SecureFileError:
            return None

    def get(self, endpoint):
        if endpoint not in self.PATHS:
            raise LuckyAPIError("not_found", 404)
        return self._get_path(self.PATHS[endpoint])

    def get_web_rule(self, rule_key):
        key = str(rule_key or "").strip()
        if not re.fullmatch(r"[0-9A-Za-z_-]{1,128}", key):
            raise LuckyAPIError("schema_mismatch")
        return self._get_path("/api/webservice/rule/" + urllib.parse.quote(key, safe=""))

    def _get_path(self, path):
        token = self._token() if self.auth_mode != "none" else None
        headers = {"Accept": "application/json"}
        if token and self.auth_mode != "none":
            header_name = "Lucky-Admin-Token" if self.auth_mode == "admin_token" else "openToken"
            headers[header_name] = token
        if self.request_func:
            return self._unwrap(self.request_func(path, dict(headers)))
        request = urllib.request.Request(self.base_url + path, headers=headers, method="GET")
        handlers = [_NoRedirect()]
        if request.full_url.startswith("https://") and not self.verify_tls:
            handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        opener = urllib.request.build_opener(*handlers)
        try:
            with opener.open(request, timeout=self.timeout) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                if "json" not in content_type:
                    raise LuckyAPIError("invalid_response", response.status)
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise LuckyAPIError("response_too_large", response.status)
        except urllib.error.HTTPError as exc:
            code = {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(exc.code, "invalid_response")
            raise LuckyAPIError(code, exc.code)
        except (socket.timeout, TimeoutError):
            raise LuckyAPIError("timeout")
        except (urllib.error.URLError, OSError):
            raise LuckyAPIError("connection_refused")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise LuckyAPIError("invalid_response")
        return self._unwrap(payload)

    @staticmethod
    def _unwrap(payload):
        if not isinstance(payload, dict):
            raise LuckyAPIError("schema_mismatch")
        if "ret" in payload and payload.get("ret") not in (0, "0", True):
            raise LuckyAPIError("invalid_response")
        return payload.get("data", payload)


def _pick(value, *names, default=None):
    if not isinstance(value, dict):
        return default
    lowered = {str(key).lower(): item for key, item in value.items()}
    for name in names:
        if name in value:
            return value[name]
        if name.lower() in lowered:
            return lowered[name.lower()]
    return default


def _rows(value, *names):
    if isinstance(value, list):
        return value[:MAX_ITEMS]
    candidate = _pick(value, *names, default=[])
    return candidate[:MAX_ITEMS] if isinstance(candidate, list) else []


def _stable_id(prefix, value, index):
    material = _safe_text(value, MAX_NAME, str(index))
    digest = hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()[:12]
    return "%s-%s" % (prefix, digest)


def _local_timezone():
    return datetime.datetime.now().astimezone().tzinfo or datetime.timezone.utc


def _parse_time(value, default_timezone=None):
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if value > 100000000000 else value
        try:
            return _timestamp(datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc))
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                timezone = default_timezone or _local_timezone()
                parsed = datetime.datetime.strptime(text, pattern).replace(tzinfo=timezone)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_timezone or _local_timezone())
    return _timestamp(parsed)


def _version_parts(value):
    if not value:
        return None
    match = re.match(
        r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$",
        str(value).strip(),
    )
    if not match:
        return None
    prerelease = match.group(4)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))), (prerelease.split(".") if prerelease else None)


def _compare_prerelease(left, right):
    if left is None or right is None:
        return 0 if left is right else (1 if left is None else -1)
    for left_part, right_part in zip(left, right):
        if left_part == right_part:
            continue
        left_numeric, right_numeric = left_part.isdigit(), right_part.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_part) < int(right_part) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_part < right_part else 1
    return (len(left) > len(right)) - (len(left) < len(right))


def compare_versions(current, latest):
    left, right = _version_parts(current), _version_parts(latest)
    if left is None or right is None:
        return None
    if left[0] != right[0]:
        return left[0] < right[0]
    return _compare_prerelease(left[1], right[1]) < 0


def _module_error(exc, source):
    return _error(exc.code, _error_message(exc.code), source, exc.code in ("timeout", "connection_refused"), exc.http_status)


def _normalize_collection(payload, key, prefix, now, normalizer):
    rows = _rows(payload, key, "list", "items", "data")
    items = [normalizer(row, index) for index, row in enumerate(rows) if isinstance(row, dict)]
    enabled = sum(1 for item in items if item.get("enabled") is True)
    healthy = sum(1 for item in items if item.get("status") in ("ok", "healthy", "running", "active"))
    errors = sum(1 for item in items if item.get("status") in ("error", "failed", "invalid"))
    return {
        "total": len(items), "enabled": enabled, "disabled": len(items) - enabled,
        "healthy": healthy, "error_count": errors, key: items,
        "status": "degraded" if errors else "ok", "stale": False,
        "updated_at": now, "error": None,
    }


def _change_status(value):
    changed = _safe_bool(value, None)
    if changed is not None:
        return "changed" if changed else "unchanged"
    return _safe_text(value, 32)


def _nested_count(row, names):
    value = _pick(row, *names)
    return len(value) if isinstance(value, list) else None


def _ddns_address_method(row):
    explicit = _safe_text(
        _pick(row, "GetIpType", "IPGetType", "AddressSource", "GetIPMode", "address_method"),
        MAX_TEXT,
    )
    if explicit:
        return explicit
    task_type = (_safe_text(_pick(row, "TaskType", "Type"), 32, "") or "").lower()
    ipv4_method = _safe_text(_pick(row, "V4QueryIPType", "IPv4QueryIPType"), MAX_TEXT)
    ipv6_method = _safe_text(_pick(row, "V6QueryIPType", "IPv6QueryIPType"), MAX_TEXT)
    if "6" in task_type and ipv6_method:
        return ipv6_method
    if "4" in task_type and ipv4_method:
        return ipv4_method
    methods = []
    for method in (ipv4_method, ipv6_method):
        if method and method not in methods:
            methods.append(method)
    return " / ".join(methods) or None


def _ddns_record_summary(row):
    records = _pick(row, "DomainRecords", "Domains", "Records")
    if not isinstance(records, list):
        return None, None
    statuses = [
        str(_pick(record, "UpdateStatus", "Status", default="")).strip().lower()
        for record in records
        if isinstance(record, dict)
    ]
    statuses = [status for status in statuses if status]
    if not statuses:
        return None, None
    if any("error" in status or "fail" in status for status in statuses):
        change_status = "error"
    elif any("nochange" not in status and ("change" in status or "update" in status or "success" in status) for status in statuses):
        change_status = "changed"
    elif all("nochange" in status for status in statuses):
        change_status = "unchanged"
    else:
        change_status = _safe_text(statuses[0], 32)
    updated = sum(
        1
        for status in statuses
        if "nochange" not in status and ("change" in status or "update" in status or "success" in status)
    )
    return change_status, updated


def _record(row, index, local_timezone=None):
    name = _pick(row, "Remark", "Name", "TaskName", "name")
    status = _safe_text(_pick(row, "Status", "state", "RunStatus"), 32, "unknown").lower()
    dns = _pick(row, "DNS", default={})
    if not isinstance(dns, dict):
        dns = {}
    nested_change_status, nested_updated_records = _ddns_record_summary(row)
    total_records = _safe_int(
        _pick(row, "TotalRecordCount", "DomainCount", "RecordCount", "total_records"),
        _nested_count(row, ("DomainRecords", "Domains", "Records")),
    )
    updated_records = _safe_int(
        _pick(row, "UpdatedRecordCount", "UpdatedDomainCount", "SuccessCount", "updated_records"),
        nested_updated_records,
    )
    if updated_records is not None and total_records is not None and updated_records > total_records:
        updated_records = None
    return {
        "id": _stable_id("ddns", _pick(row, "Key", "ID", "id", default=name), index),
        "display_name": _safe_text(name, MAX_NAME, "DDNS record %d" % (index + 1)),
        "provider": _safe_text(
            _pick(row, "Provider", "DNSProvider", "provider", default=_pick(dns, "Name")),
            64,
        ),
        "address_method": _ddns_address_method(row),
        "local_record_change_status": _change_status(
            _pick(
                row,
                "LocalRecordChanged",
                "RecordChanged",
                "IPChanged",
                "local_record_changed",
                default=nested_change_status,
            )
        ),
        "updated_records": updated_records,
        "total_records": total_records,
        "enabled": _safe_bool(_pick(row, "Enable", "Enabled", "enabled"), False),
        "status": status, "record_type": _safe_text(_pick(row, "Type", "RecordType", "TaskType"), 32),
        "last_update_at": _parse_time(_pick(row, "LastSyncTime", "UpdateTime", "LastUpdateTime"), local_timezone),
        "next_sync_at": _parse_time(_pick(row, "NextSyncTime", "NextUpdateTime"), local_timezone),
        "last_success_at": _parse_time(_pick(row, "SuccessTime", "LastSuccessTime"), local_timezone),
        "error": None if status not in ("error", "failed") else _error("module_error", "Lucky record reported an error", "lucky.ddns"),
    }


def _web_service(row, index):
    name = _pick(row, "Remark", "Name", "RuleName", "name")
    status = _safe_text(_pick(row, "Status", "state"), 32, "unknown").lower()
    subrules = _pick(row, "SubRules", "Rules", "subrules")
    total_subrules = _safe_int(
        _pick(row, "TotalSubRuleCount", "SubRuleCount", "total_subrules"),
        len(subrules) if isinstance(subrules, list) else None,
    )
    enabled_subrules = _safe_int(_pick(row, "EnabledSubRuleCount", "SubRulesEnabled", "enabled_subrules"), None)
    if enabled_subrules is None and isinstance(subrules, list):
        enabled_subrules = sum(1 for item in subrules if isinstance(item, dict) and _safe_bool(_pick(item, "Enable", "Enabled", "enabled"), False))
    if enabled_subrules is not None and total_subrules is not None and enabled_subrules > total_subrules:
        enabled_subrules = None
    return {
        "id": _stable_id("web", _pick(row, "Key", "ID", "id", default=name), index),
        "display_name": _safe_text(name, MAX_NAME, "Web service %d" % (index + 1)),
        "enabled": _safe_bool(_pick(row, "Enable", "Enabled", "enabled"), False),
        "status": status,
        "protocol": _safe_text(_pick(row, "Protocol", "Scheme", "Network", "protocol"), 16, "unknown").lower(),
        "listen_port": _safe_int(_pick(row, "Port", "ListenPort", "listen_port"), None, 1, 65535),
        "upstream_type": _safe_text(_pick(row, "UpstreamType", "ProxyType"), 32),
        "tls_enabled": _safe_bool(_pick(row, "TLS", "TLSEnable", "HTTPS", "tls_enabled"), False),
        "certificate_ref": _safe_text(_pick(row, "CertRemark", "CertificateName"), MAX_NAME),
        "connection_count": _safe_int(_pick(row, "ConnectionCount", "Connections", "connection_count")),
        "enabled_subrules": enabled_subrules,
        "total_subrules": total_subrules,
        "error": None if status not in ("error", "failed") else _error("module_error", "Lucky web service reported an error", "lucky.web"),
    }


def _statistics_for_rule(statistics, rule_key):
    if not isinstance(statistics, dict) or rule_key is None:
        return {}
    result = statistics.get(rule_key)
    if result is None:
        result = statistics.get(str(rule_key))
    return result if isinstance(result, dict) else {}


def _prepare_web_service(lite_row, rule_payload, statistics):
    rule = _pick(rule_payload, "rule", default=rule_payload)
    if not isinstance(rule, dict):
        rule = {}
    item = dict(rule)
    key = _pick(lite_row, "Key", "RuleKey", "ID", "id")
    item.setdefault("Key", key)
    item.setdefault("Name", _pick(lite_row, "Name", "RuleName", "Remark"))
    proxy_list = _pick(rule, "ProxyList", "SubRules", default=[])
    if not isinstance(proxy_list, list):
        proxy_list = []
    item["SubRules"] = proxy_list
    item["TotalSubRuleCount"] = len(proxy_list)
    item["EnabledSubRuleCount"] = sum(
        1 for subrule in proxy_list
        if isinstance(subrule, dict) and _safe_bool(_pick(subrule, "Enable", "Enabled"), False)
    )
    item["Enable"] = item["EnabledSubRuleCount"] > 0
    item["Status"] = "running" if item["Enable"] else "disabled"
    item["ConnectionCount"] = _safe_int(
        _pick(_statistics_for_rule(statistics, key), "Connections"),
        None,
    )
    return item


def _ddns_resolution_summary(payload, updated_at, error=None):
    if error is not None:
        return {
            "mode": "ddns_records", "resolved_ip_count": 0, "ipv4_count": 0,
            "ipv6_count": 0, "status": "error", "updated_at": None,
            "stale": True, "error": error,
        }
    normal = 0
    ipv4 = 0
    ipv6 = 0
    total = 0
    for row in _rows(payload, "records", "list", "items", "data"):
        if not isinstance(row, dict):
            continue
        task_type = (_safe_text(_pick(row, "TaskType", "Type"), 32, "") or "").lower()
        records = _pick(row, "DomainRecords", "Domains", "Records", default=[])
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            total += 1
            status = str(_pick(record, "UpdateStatus", "Status", default="")).strip().lower()
            is_normal = bool(status) and "fail" not in status and "error" not in status
            if not is_normal:
                continue
            normal += 1
            if "6" in task_type:
                ipv6 += 1
            elif "4" in task_type:
                ipv4 += 1
    return {
        "mode": "ddns_records", "resolved_ip_count": normal,
        "ipv4_count": ipv4, "ipv6_count": ipv6,
        "status": "ok" if total == normal else "degraded",
        "updated_at": updated_at, "stale": False, "error": None,
    }


def _forward(row, index):
    name = _pick(row, "Remark", "Name", "name")
    status = _safe_text(_pick(row, "Status", "state"), 32, "unknown").lower()
    protocol = _pick(row, "Protocol", "Type", "protocol", "ForwardTypes")
    if isinstance(protocol, list):
        protocol = "/".join(
            str(value).strip()
            for value in protocol
            if str(value).strip()
        )
    return {
        "id": _stable_id("forward", _pick(row, "Key", "ID", "id", default=name), index),
        "display_name": _safe_text(name, MAX_NAME, "Port forward %d" % (index + 1)),
        "enabled": _safe_bool(_pick(row, "Enable", "Enabled", "enabled"), False),
        "status": status,
        "protocol": _safe_text(protocol, 16, "unknown").lower(),
        "listen_port": _safe_int(_pick(row, "Port", "ListenPort", "listen_port", "ListenPorts"), None, 1, 65535),
        "target_type": _safe_text(_pick(row, "TargetType", "ForwardType"), 32),
        "connection_count": _safe_int(_pick(row, "ConnectionCount", "Connections", "connection_count")),
        "error": None if status not in ("error", "failed") else _error("module_error", "Lucky port forward reported an error", "lucky.forward"),
    }


def _normalize_port_forwards(payload, now):
    rows = _rows(payload, "rules", "list", "items", "data")
    statistics = _pick(payload, "statistics", "Statistics", default={})
    prepared = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        key = _pick(row, "Key", "ID", "id")
        counters = None
        if isinstance(statistics, dict) and key is not None:
            counters = statistics.get(key)
            if counters is None:
                counters = statistics.get(str(key))
        if isinstance(counters, dict):
            tcp = _safe_int(_pick(counters, "TCPCurrentConnections"), 0)
            udp = _safe_int(_pick(counters, "UDPCurrentConnections"), 0)
            item["ConnectionCount"] = tcp + udp
        prepared.append(item)
    return _normalize_collection(prepared, "rules", "forward", now, _forward)


def _certificate_status(not_before, not_after, now, warning_days, explicit_error=False):
    if explicit_error or not not_before or not not_after:
        return "invalid" if explicit_error else "unknown", None
    try:
        before = datetime.datetime.fromisoformat(not_before.replace("Z", "+00:00"))
        after = datetime.datetime.fromisoformat(not_after.replace("Z", "+00:00"))
    except ValueError:
        return "invalid", None
    current = now if now.tzinfo else now.replace(tzinfo=datetime.timezone.utc)
    remaining = int((after - current).total_seconds() // 86400)
    if current < before:
        return "not_yet_valid", remaining
    if current > after:
        return "expired", remaining
    if remaining <= warning_days:
        return "expiring", remaining
    return "valid", remaining


def _certificate(row, index, now, warning_days, local_timezone=None):
    info = _pick(row, "CertsInfo", "CertificateInfo", default={})
    if not isinstance(info, dict):
        info = {}
    name = _pick(row, "Remark", "Name", "name")
    not_before = _parse_time(_pick(info, "NotBeforeTime", "NotBefore", default=_pick(row, "NotBeforeTime")), local_timezone)
    not_after = _parse_time(_pick(info, "NotAfterTime", "NotAfter", default=_pick(row, "NotAfterTime")), local_timezone)
    explicit_error = bool(_pick(row, "ErrMsg", "ACMEErrMsg", "Error"))
    status, remaining = _certificate_status(not_before, not_after, now, warning_days, explicit_error)
    return {
        "id": _stable_id("cert", _pick(row, "Key", "ID", "id", default=name), index),
        "display_name": _safe_text(name, MAX_NAME, "Certificate %d" % (index + 1)),
        "san_count": _safe_int(_pick(info, "SANCount", "DnsNamesCount", default=len(_pick(info, "DNSNames", default=[]) or [])), 0),
        "issuer": _safe_text(_pick(info, "Issuer", "IssuerName"), MAX_NAME),
        "source": _safe_text(_pick(row, "Type", "Source"), 32, "unknown").lower(),
        "not_before": not_before, "not_after": not_after, "remaining_days": remaining,
        "status": status, "auto_renew": _safe_bool(_pick(row, "AutoRenew", "Enable"), None),
        "last_renew_at": _parse_time(_pick(row, "UpdateTime", "LastRenewTime"), local_timezone),
        "next_renew_at": _parse_time(_pick(row, "NextRenewTime"), local_timezone),
        "error": _error("certificate_parse_failed", "Certificate status could not be determined", "lucky.certificates") if status == "invalid" else None,
    }


class LuckyCollector(object):
    def __init__(self, enabled=False, base_url=DEFAULT_LUCKY_BASE_URL, auth_mode="none",
                 token_file=None, timeout=5, warning_days=30, version_check_ttl=21600,
                 verify_tls=True, request_func=None, local_timezone=None, process_state_func=None):
        self.enabled = bool(enabled)
        self.warning_days = _bounded_config_int(warning_days, 30, 1, 365)
        self.version_check_ttl = _bounded_config_int(version_check_ttl, 21600, 3600, 86400)
        self._latest_cache = None
        self.local_timezone = local_timezone or _local_timezone()
        self.process_state_func = process_state_func or lucky_process_state
        self.client = None
        self.configuration_error = None
        if self.enabled:
            try:
                request_timeout = _bounded_config_int(timeout, 5, 1, 30)
                self.client = LuckyClient(
                    base_url, auth_mode, token_file, request_timeout, verify_tls, request_func
                )
            except (TypeError, ValueError):
                self.configuration_error = _error(
                    "invalid_configuration",
                    _error_message("invalid_configuration"),
                    "lucky.config",
                )

    def _collect_module(self, endpoint, builder, now):
        try:
            return builder(self.client.get(endpoint))
        except LuckyAPIError as exc:
            error = _module_error(exc, "lucky.%s" % endpoint)
        except Exception:
            error = _error("schema_mismatch", _error_message("schema_mismatch"), "lucky.%s" % endpoint)
        result = _empty_collection({"ddns": "records", "web": "services", "forward": "rules"}.get(endpoint, "items"), "error", error)
        result["updated_at"] = now
        return result

    def _collect_web_services(self, now):
        try:
            primary_payload = self.client.get("web")
            rows = _rows(primary_payload, "rulelist", "rules", "list", "items", "data")
            statistics = _pick(primary_payload, "statistics", "Statistics", default={})
            prepared = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                item = dict(row)
                key = _pick(row, "Key", "RuleKey", "ID", "id")
                counters = _statistics_for_rule(statistics, key)
                if _pick(item, "ConnectionCount", "Connections", "connection_count") is None:
                    item["ConnectionCount"] = _safe_int(_pick(counters, "Connections"), None)
                prepared.append(item)
            return _normalize_collection(prepared, "services", "web", now, _web_service)
        except LuckyAPIError as exc:
            primary_error = exc
        except Exception:
            primary_error = None

        try:
            lite_payload = self.client.get("web_lite")
        except LuckyAPIError as exc:
            error = _module_error(exc, "lucky.web")
        except Exception:
            error = _error("schema_mismatch", _error_message("schema_mismatch"), "lucky.web")
        else:
            error = None

        if error is not None:
            if isinstance(primary_error, LuckyAPIError):
                error = _module_error(primary_error, "lucky.web")
            result = _empty_collection("services", "error", error)
            result["updated_at"] = now
            return result

        prepared = []
        errors = []
        for lite_row in _rows(lite_payload, "rulelist", "rules", "list", "items", "data"):
            if not isinstance(lite_row, dict):
                continue
            key = _pick(lite_row, "Key", "RuleKey", "ID", "id")
            try:
                rule_payload = self.client.get_web_rule(key)
            except LuckyAPIError as exc:
                errors.append(_module_error(exc, "lucky.web.rule"))
                rule_payload = {}
            except Exception:
                errors.append(_error("schema_mismatch", _error_message("schema_mismatch"), "lucky.web.rule"))
                rule_payload = {}
            item = _prepare_web_service(lite_row, rule_payload, {})
            if errors and not _pick(rule_payload, "rule", default=rule_payload):
                item["Status"] = "error"
                item["Error"] = errors[-1]
            prepared.append(item)

        result = _normalize_collection(prepared, "services", "web", now, _web_service)
        if errors:
            result["status"] = "degraded"
            result["error_count"] = len(errors)
            result["error"] = errors[0]
        return result

    def collect(self, now=None):
        if not self.enabled:
            return not_configured_lucky()
        if self.configuration_error is not None:
            return unavailable_lucky("invalid_configuration")
        now_dt = now or datetime.datetime.now(datetime.timezone.utc)
        collected_at = _timestamp(now_dt)
        try:
            process_running, process_pid = self.process_state_func()
        except Exception:
            process_running, process_pid = None, None
        try:
            version_payload = self.client.get("version")
        except LuckyAPIError as exc:
            # Lucky's fixed version endpoint may redirect before its local
            # backend error is exposed.  The fixed info endpoint is already
            # part of the read-only allowlist; use it only to retain the
            # bounded backend failure (for example HTTP 502), never to follow
            # a redirect or turn a failed API into healthy data.
            if exc.code == "invalid_response" and exc.http_status in (301, 302, 303, 307, 308):
                try:
                    self.client.get("info")
                except LuckyAPIError as diagnostic_error:
                    exc = diagnostic_error
            return unavailable_lucky(
                exc.code, exc.http_status, process_running, process_pid
            )

        current = _safe_text(_pick(version_payload, "version", "Version"), 64)
        build_info = _safe_text(_pick(version_payload, "buildTime", "BuildTime", "build_info"), 128)
        status_payload = {}
        source_errors = {}
        for endpoint in ("status",):
            try:
                value = self.client.get(endpoint)
            except LuckyAPIError as exc:
                source_errors[endpoint] = _module_error(exc, "lucky.%s" % endpoint)
                continue
            status_payload = value

        version = {
            "current": current, "latest": None, "update_available": None,
            "build_info": build_info, "checked_at": None,
            "stale": False, "error": None,
        }
        service_error = source_errors.get("status")
        service = {
            "state": "running" if process_running is not False else "stopped",
            "process_running": process_running,
            "process_pid": process_pid or _safe_int(_pick(status_payload, "PID", "pid")),
            "uptime_seconds": _safe_int(_pick(status_payload, "Uptime", "uptime", "uptime_seconds")),
            "api_reachable": "status" not in source_errors, "web_reachable": True, "error": service_error,
        }
        try:
            ddns_payload = self.client.get("ddns")
            ddns = _normalize_collection(
                ddns_payload, "records", "ddns", collected_at,
                lambda row, index: _record(row, index, self.local_timezone),
            )
            ip_resolution = _ddns_resolution_summary(ddns_payload, collected_at)
        except LuckyAPIError as exc:
            ddns_error = _module_error(exc, "lucky.ddns")
            ddns = _empty_collection("records", "error", ddns_error)
            ddns["updated_at"] = collected_at
            ip_resolution = _ddns_resolution_summary({}, collected_at, ddns_error)
        except Exception:
            ddns_error = _error("schema_mismatch", _error_message("schema_mismatch"), "lucky.ddns")
            ddns = _empty_collection("records", "error", ddns_error)
            ddns["updated_at"] = collected_at
            ip_resolution = _ddns_resolution_summary({}, collected_at, ddns_error)
        web = self._collect_web_services(collected_at)
        forward = self._collect_module("forward", lambda value: _normalize_port_forwards(value, collected_at), collected_at)
        try:
            cert_rows = _rows(self.client.get("ssl"), "items", "list", "certificates", "data")
            cert_items = [
                _certificate(row, index, now_dt, self.warning_days, self.local_timezone)
                for index, row in enumerate(cert_rows) if isinstance(row, dict)
            ]
            counts = {name: sum(1 for item in cert_items if item["status"] == name) for name in ("valid", "expiring", "expired", "not_yet_valid", "invalid", "unknown")}
            certificates = {
                "total": len(cert_items), **counts, "items": cert_items,
                "status": "degraded" if counts["invalid"] else "ok", "stale": False,
                "updated_at": collected_at, "error": None,
            }
        except LuckyAPIError as exc:
            certificates = _empty_certificates("error", _module_error(exc, "lucky.ssl"))
            certificates["updated_at"] = collected_at
        except Exception:
            certificates = _empty_certificates("error", _error("schema_mismatch", _error_message("schema_mismatch"), "lucky.ssl"))
            certificates["updated_at"] = collected_at

        modules = (ddns, web, forward, certificates)
        failed = sum(1 for module in modules if module["error"] is not None)
        overall = "ok" if failed == 0 and not source_errors else "degraded"
        return {
            "status": overall, "source": "local_api", "service": service, "version": version,
            "ip_resolution": ip_resolution, "dynamic_dns": ddns, "web_services": web,
            "port_forwards": forward, "certificates": certificates,
            "updated_at": collected_at, "stale": False, "error": None,
        }


def collector_from_environment(request_func=None):
    enabled = os.getenv("LUCKY_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return LuckyCollector(enabled=False)
    verify_tls = os.getenv("LUCKY_VERIFY_TLS", "true").strip().lower() not in ("0", "false", "no", "off")
    return LuckyCollector(
        enabled=enabled,
        base_url=os.getenv("LUCKY_BASE_URL", DEFAULT_LUCKY_BASE_URL),
        auth_mode=os.getenv("LUCKY_AUTH_MODE", "none"),
        token_file=os.getenv("LUCKY_TOKEN_FILE") or None,
        timeout=os.getenv("LUCKY_TIMEOUT_SECONDS", "5"),
        warning_days=os.getenv("LUCKY_CERT_WARNING_DAYS", "30"),
        version_check_ttl=os.getenv("LUCKY_VERSION_CHECK_TTL", "21600"),
        verify_tls=verify_tls,
        request_func=request_func,
    )
