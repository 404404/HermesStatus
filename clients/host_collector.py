#!/usr/bin/env python3
"""Collect the Release A host extensions without blocking native updates."""

import copy
import datetime
import glob
import json
import os
import re
import shlex
import socket
import subprocess
import tempfile
import threading
import time


EXTENSION_VERSION = "1.0-draft"
REDACTED_VALUE = "[redacted]"

MAX_CPU_MODEL_LENGTH = 128
MAX_TEMPERATURE_SOURCE_LENGTH = 128
MAX_DISK_DEVICE_LENGTH = 128
MAX_DISK_SMART_SOURCE_LENGTH = 64
MAX_DOCKER_CONTAINERS = 256
MAX_DOCKER_COUNT = 100000
MAX_SAFE_INTEGER = 9007199254740991
MAX_DOCKER_NAME_LENGTH = 256
MAX_DOCKER_STATUS_LENGTH = 128
MAX_DOCKER_IMAGE_LENGTH = 256
MAX_DOCKER_PORTS_LENGTH = 512
MAX_HERMES_PROFILES = 64

SMART_TIMEOUT_SECONDS = 12
DOCKER_TIMEOUT_SECONDS = 4
MAX_DOCKER_RESPONSE_BYTES = 4 * 1024 * 1024

_SECRET_PATTERNS = (
    re.compile(r"authorization\s*:", re.I),
    re.compile(r"\bbearer\s+\S+", re.I),
    re.compile(
        r"(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|password|passwd|secret|credential|token)\s*[:=]",
        re.I,
    ),
    re.compile(r"--(token|password)(=|\s+)", re.I),
    re.compile(r"[?&](api[_-]?key|key|token|password)=", re.I),
)


def _env_int(name, default, minimum=1):
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _truncate(value, limit, empty="-"):
    text = " ".join(str(value or "").split())
    if not text:
        text = empty
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        return REDACTED_VALUE
    return text[:limit]


def _nullable_text(value, limit):
    text = " ".join(str(value or "").split())
    if not text:
        return None
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        return REDACTED_VALUE
    return text[:limit]


def _utc_timestamp(now=None):
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    return now.astimezone(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _error(code, message, source, retryable=False, http_status=None):
    return {
        "code": code[:64],
        "message": message[:256],
        "source": source[:64],
        "retryable": bool(retryable),
        "http_status": http_status,
    }


def not_reported_hardware():
    return {
        "cpu_model": None,
        "cpu_temperature": None,
        "disk_temperature": None,
        "disk_smart_status": "unknown",
        "disk_power_on_hours": None,
        "disk_written_bytes": None,
        "disk_read_bytes": None,
        "disk_device": None,
        "disk_smart_source": None,
        "updated_at": None,
        "stale": True,
        "error": _error("not_reported", "Extension data was not reported", "hardware"),
    }


def not_reported_docker():
    return {
        "running": 0,
        "total": 0,
        "limit": 0,
        "truncated": False,
        "containers": [],
        "updated_at": None,
        "stale": True,
        "error": _error("not_reported", "Extension data was not reported", "docker"),
    }


def not_reported_hermes():
    return {
        "profiles": [],
        "updated_at": None,
        "stale": True,
        "error": _error("not_reported", "Extension data was not reported", "hermes"),
    }


def read_hermes_snapshot(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            payload = json.load(handle)
    except (OSError, TypeError, ValueError):
        payload = None
    if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
        result = not_reported_hermes()
        result["error"] = _error(
            "snapshot_unavailable",
            "Hermes integration snapshot is unavailable",
            "hermes-snapshot",
            True,
        )
        return result
    profiles = payload.get("profiles")[:MAX_HERMES_PROFILES]
    if not all(isinstance(item, dict) for item in profiles):
        result = not_reported_hermes()
        result["error"] = _error(
            "snapshot_invalid",
            "Hermes integration snapshot is invalid",
            "hermes-snapshot",
            True,
        )
        return result
    return {
        "profiles": profiles,
        "updated_at": payload.get("updated_at"),
        "stale": bool(payload.get("stale", True)),
        "error": payload.get("error") if isinstance(payload.get("error"), dict) else None,
    }


def read_os_release(path):
    values = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                values[key.strip()] = value.replace(r"\"", '"')
    except (OSError, UnicodeError):
        return {}
    return values


def collect_host_os(path):
    values = read_os_release(path)
    if not values:
        return "unknown", _error(
            "host_os_unavailable",
            "Host operating system data is unavailable",
            "host-os",
            True,
        )
    pretty = values.get("PRETTY_NAME")
    if pretty:
        return _truncate(pretty, 128, "unknown"), None
    name = values.get("NAME") or values.get("ID")
    version = values.get("VERSION_ID") or values.get("VERSION")
    display = " ".join(part for part in (name, version) if part)
    if display:
        return _truncate(display, 128, "unknown"), None
    return "unknown", _error(
        "host_os_unavailable",
        "Host operating system data is unavailable",
        "host-os",
        False,
    )


def _default_command_runner(command, timeout):
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=timeout,
        env=dict(os.environ, LC_ALL="C"),
    )
    return completed.returncode, completed.stdout or ""


def _cpu_model_from_lscpu_json(output):
    try:
        data = json.loads(output)
    except (TypeError, ValueError):
        return None
    for item in data.get("lscpu", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip().rstrip(":").lower()
        if field == "model name":
            return _nullable_text(item.get("data"), MAX_CPU_MODEL_LENGTH)
    return None


def collect_cpu_model(command_runner=None, cpuinfo_path="/proc/cpuinfo"):
    runner = command_runner or _default_command_runner
    model = None
    try:
        returncode, output = runner(["lscpu", "--json"], 3)
        if returncode == 0:
            model = _cpu_model_from_lscpu_json(output)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    if not model:
        try:
            with open(cpuinfo_path, "r", encoding="utf-8", errors="replace") as handle:
                fallback = None
                for line in handle:
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    if key == "model name":
                        model = _nullable_text(value, MAX_CPU_MODEL_LENGTH)
                        break
                    if key in ("hardware", "processor") and not str(value).strip().isdigit():
                        fallback = fallback or _nullable_text(value, MAX_CPU_MODEL_LENGTH)
                model = model or fallback
        except OSError:
            pass
    if model:
        return model, None
    return None, _error(
        "cpu_model_unavailable",
        "Host CPU model is unavailable",
        "cpu-model",
        False,
    )


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def collect_hwmon_temperatures(root="/sys/class/hwmon"):
    sensors = []
    for base in sorted(glob.glob(os.path.join(root, "hwmon*"))):
        chip = _read_text(os.path.join(base, "name")) or os.path.basename(base)
        for input_path in sorted(glob.glob(os.path.join(base, "temp*_input"))):
            match = re.search(r"temp(\d+)_input$", input_path)
            index = match.group(1) if match else ""
            label = _read_text(os.path.join(base, "temp%s_label" % index))
            raw_value = _read_text(input_path)
            try:
                value = int(raw_value) / 1000.0
            except (TypeError, ValueError):
                continue
            if value < -100 or value > 250:
                continue
            source = " ".join(part for part in (chip, label) if part).strip() or chip
            sensors.append(
                {
                    "value": round(value, 1),
                    "source": _truncate(source, MAX_TEMPERATURE_SOURCE_LENGTH, "hwmon"),
                }
            )
    return sensors


def pick_cpu_temperature(sensors):
    keywords = ("coretemp", "cpu", "package", "k10temp")
    fallback = sensors[0] if sensors else None
    for sensor in sensors:
        source = str(sensor.get("source") or "").lower()
        if any(keyword in source for keyword in keywords):
            return sensor
    return fallback


def _parse_smart_device(value):
    try:
        parts = shlex.split(value)
    except ValueError:
        return None
    if not parts:
        return None
    device = next((part for part in parts if part.startswith("/dev/")), "")
    device_type = ""
    if "-d" in parts:
        index = parts.index("-d")
        if index + 1 < len(parts):
            device_type = parts[index + 1]
    if not device.startswith("/dev/"):
        return None
    return device, device_type


def _base_block_device(device):
    if re.match(r"^/dev/(?:sd|vd|hd|xvd)[a-z]+\d+$", device):
        return re.sub(r"\d+$", "", device)
    return re.sub(r"p\d+$", "", device)


def smart_candidates(configured="auto", command_runner=None):
    runner = command_runner or _default_command_runner
    if configured and configured != "auto":
        candidate = _parse_smart_device(configured)
        return [candidate] if candidate else []

    devices = []
    try:
        _, output = runner(["smartctl", "--scan"], 4)
        for line in output.splitlines():
            candidate = _parse_smart_device(line.split("#", 1)[0].strip())
            if candidate and candidate not in devices:
                devices.append(candidate)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                device = line.split(None, 1)[0] if line.strip() else ""
                if not device.startswith("/dev/"):
                    continue
                device = _base_block_device(device)
                candidate = (device, "")
                if candidate not in devices:
                    devices.append(candidate)
    except OSError:
        pass
    for pattern in ("/dev/nvme*n1", "/dev/sd?", "/dev/vd?"):
        for device in sorted(glob.glob(pattern)):
            candidate = (device, "")
            if candidate not in devices:
                devices.append(candidate)
    return devices


def _coerce_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, dict):
        for key in ("value", "raw", "current"):
            if key in value:
                found = _coerce_int(value[key])
                if found is not None:
                    return found
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _hex_or_int(value):
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def _device_stat_json_value(data, page_number, offset, description):
    statistics = data.get("ata_device_statistics") if isinstance(data, dict) else None
    pages = statistics.get("pages", []) if isinstance(statistics, dict) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_value = _hex_or_int(page.get("number", page.get("page")))
        if page_value != page_number:
            continue
        for item in page.get("table", page.get("entries", [])) or []:
            if not isinstance(item, dict):
                continue
            item_offset = _hex_or_int(item.get("offset"))
            item_name = str(item.get("name") or item.get("description") or "").strip().lower()
            if item_offset == offset or item_name == description.lower():
                result = _coerce_int(item.get("value", item.get("raw")))
                if result is not None:
                    return result
    return None


def _device_stat_text_value(text, page, offset, description):
    pattern = re.compile(
        r"^\s*%s\s+%s\s+\d+\s+(-?\d+)\s+---\s+%s\s*$"
        % (re.escape(page), re.escape(offset), re.escape(description)),
        re.I | re.M,
    )
    match = pattern.search(text or "")
    return int(match.group(1)) if match else None


def _smart_health(data, text):
    match = re.search(
        r"SMART overall-health self-assessment test result:\s*([A-Z]+)",
        text or "",
        re.I,
    )
    if match:
        result = match.group(1).lower()
        return "passed" if result == "passed" else "failed"
    status = data.get("smart_status") if isinstance(data, dict) else None
    if isinstance(status, dict) and isinstance(status.get("passed"), bool):
        return "passed" if status["passed"] else "failed"
    return "unknown"


def _json_nested_value(data, keys):
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in keys:
                result = _coerce_int(value)
                if result is not None:
                    return result
            result = _json_nested_value(value, keys)
            if result is not None:
                return result
    elif isinstance(data, list):
        for value in data:
            result = _json_nested_value(value, keys)
            if result is not None:
                return result
    return None


def _logical_sector_size(data, text):
    size = _json_nested_value(data, {"logical_block_size", "logical_sector_size"})
    if size is None:
        patterns = (
            r"Sector Size:\s*(\d+)\s+bytes logical",
            r"Logical (?:block|sector) size:\s*(\d+)\s+bytes",
        )
        for pattern in patterns:
            match = re.search(pattern, text or "", re.I)
            if match:
                size = int(match.group(1))
                break
    if size is None or size < 128 or size > 1048576:
        return None
    return size


def _smart_values(data, text):
    def stat(page_number, page_text, offset, description):
        value = _device_stat_json_value(data, page_number, int(offset, 16), description)
        if value is None:
            value = _device_stat_text_value(text, page_text, offset, description)
        return value

    current = stat(5, "0x05", "0x008", "Current Temperature")
    highest = stat(5, "0x05", "0x020", "Highest Temperature")
    lowest = stat(5, "0x05", "0x028", "Lowest Temperature")
    hours = stat(1, "0x01", "0x010", "Power-on Hours")
    written_sectors = stat(1, "0x01", "0x018", "Logical Sectors Written")
    read_sectors = stat(1, "0x01", "0x028", "Logical Sectors Read")

    temperature_source = "smartctl-device-statistics"
    if current is None:
        current = _json_nested_value(data.get("temperature", {}) if isinstance(data, dict) else {}, {"current"})
        temperature_source = "smartctl-json"
    sector_size = _logical_sector_size(data, text)
    return {
        "health": _smart_health(data, text),
        "current": current,
        "highest": highest,
        "lowest": lowest,
        "hours": hours,
        "written_sectors": written_sectors,
        "read_sectors": read_sectors,
        "sector_size": sector_size,
        "temperature_source": temperature_source,
    }


def _valid_temperature(value):
    return value is None or (-100 <= value <= 250)


def _valid_counter(value):
    return value is None or (0 <= value <= MAX_SAFE_INTEGER)


def collect_smart(device="auto", command_runner=None):
    runner = command_runner or _default_command_runner
    candidates = smart_candidates(device, runner)
    if not candidates:
        return None, _error(
            "smartctl_unavailable",
            "SMART data is unavailable",
            "smartctl",
            True,
        )

    for candidate, device_type in candidates:
        typed = ["-d", device_type] if device_type else []
        data = {}
        text = ""
        json_ok = False
        try:
            _, output = runner(["smartctl", "-x", "-j"] + typed + [candidate], SMART_TIMEOUT_SECONDS)
            parsed = json.loads(output) if output else None
            if isinstance(parsed, dict):
                data = parsed
                json_ok = True
        except (OSError, subprocess.SubprocessError, TypeError, ValueError):
            pass

        # The text result remains authoritative for overall-health and Device
        # Statistics. JSON supplies structured fallbacks and sector metadata.
        try:
            _, output = runner(["smartctl", "-x"] + typed + [candidate], SMART_TIMEOUT_SECONDS)
            if "START OF READ SMART DATA SECTION" in output or "SMART overall-health" in output:
                text = output
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

        if not data and not text:
            continue
        values = _smart_values(data, text)
        invalid_value = not all(
            _valid_temperature(values[key]) for key in ("current", "highest", "lowest")
        ) or not all(
            _valid_counter(values[key])
            for key in ("hours", "written_sectors", "read_sectors")
        )
        if invalid_value:
            for key in ("current", "highest", "lowest"):
                if not _valid_temperature(values[key]):
                    values[key] = None
            for key in ("hours", "written_sectors", "read_sectors"):
                if not _valid_counter(values[key]):
                    values[key] = None
        written_bytes = None
        read_bytes = None
        sector_error = False
        if values["written_sectors"] is not None or values["read_sectors"] is not None:
            if values["sector_size"] is None:
                sector_error = True
            else:
                if values["written_sectors"] is not None:
                    written_bytes = values["written_sectors"] * values["sector_size"]
                if values["read_sectors"] is not None:
                    read_bytes = values["read_sectors"] * values["sector_size"]
                if not _valid_counter(written_bytes):
                    written_bytes = None
                    invalid_value = True
                if not _valid_counter(read_bytes):
                    read_bytes = None
                    invalid_value = True
        result = {
            "device": _nullable_text(candidate, MAX_DISK_DEVICE_LENGTH),
            "source": "smartctl-json" if json_ok and not text else ("smartctl-json-text" if json_ok else "smartctl-text"),
            "health": values["health"],
            "current": values["current"],
            "highest": values["highest"],
            "lowest": values["lowest"],
            "hours": values["hours"],
            "written_bytes": written_bytes,
            "read_bytes": read_bytes,
            "temperature_source": values["temperature_source"],
        }
        if sector_error:
            return result, _error(
                "sector_size_unknown",
                "Logical sector size is unavailable",
                "smartctl",
                False,
            )
        if invalid_value:
            return result, _error(
                "smart_value_invalid",
                "One or more SMART values are invalid",
                "smartctl",
                False,
            )
        return result, None

    return None, _error(
        "smartctl_unavailable",
        "SMART data is unavailable",
        "smartctl",
        True,
    )


def _select_error(errors):
    errors = [item for item in errors if item]
    if not errors:
        return None
    if len(errors) == 1:
        return errors[0]
    return _error(
        "partial_failure",
        "One or more extension sources are unavailable",
        "host-collector",
        any(item.get("retryable") for item in errors),
    )


def collect_hardware(
    cpu_model,
    identity_errors=None,
    hwmon_root="/sys/class/hwmon",
    smart_device="auto",
    command_runner=None,
    now=None,
):
    errors = list(identity_errors or [])
    sensors = collect_hwmon_temperatures(hwmon_root)
    cpu_temperature = pick_cpu_temperature(sensors)
    if not cpu_temperature:
        errors.append(
            _error("hwmon_unavailable", "CPU temperature is unavailable", "hwmon", True)
        )
    smart, smart_error = collect_smart(smart_device, command_runner)
    if smart_error:
        errors.append(smart_error)

    disk_temperature = None
    if smart and smart.get("current") is not None:
        disk_temperature = {
            "current": float(smart["current"]),
            "highest": float(smart["highest"]) if smart.get("highest") is not None else None,
            "lowest": float(smart["lowest"]) if smart.get("lowest") is not None else None,
            "unit": "C",
            "source": _nullable_text(smart.get("temperature_source"), MAX_TEMPERATURE_SOURCE_LENGTH),
        }

    return {
        "cpu_model": _nullable_text(cpu_model, MAX_CPU_MODEL_LENGTH),
        "cpu_temperature": {
            "value": float(cpu_temperature["value"]),
            "unit": "C",
            "source": _nullable_text(cpu_temperature.get("source"), MAX_TEMPERATURE_SOURCE_LENGTH),
        } if cpu_temperature else None,
        "disk_temperature": disk_temperature,
        "disk_smart_status": smart.get("health", "unknown") if smart else "unknown",
        "disk_power_on_hours": smart.get("hours") if smart else None,
        "disk_written_bytes": smart.get("written_bytes") if smart else None,
        "disk_read_bytes": smart.get("read_bytes") if smart else None,
        "disk_device": _nullable_text(smart.get("device"), MAX_DISK_DEVICE_LENGTH) if smart else None,
        "disk_smart_source": _nullable_text(smart.get("source"), MAX_DISK_SMART_SOURCE_LENGTH) if smart else None,
        "updated_at": _utc_timestamp(now),
        "stale": False,
        "error": _select_error(errors),
    }


def _format_ports(ports):
    values = []
    for port in ports or []:
        if not isinstance(port, dict):
            continue
        private = port.get("PrivatePort")
        public = port.get("PublicPort")
        protocol = port.get("Type") or "tcp"
        address = port.get("IP") or "0.0.0.0"
        if public and private:
            values.append("%s:%s->%s/%s" % (address, public, private, protocol))
        elif private:
            values.append("%s/%s" % (private, protocol))
    return ", ".join(values) or "-"


def _docker_request(socket_path, path, timeout=DOCKER_TIMEOUT_SECONDS):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(timeout)
        connection.connect(socket_path)
        request = "GET %s HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n" % path
        connection.sendall(request.encode("ascii"))
        chunks = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(len(item) for item in chunks) > MAX_DOCKER_RESPONSE_BYTES:
                raise ValueError("Docker response exceeds the allowed size")
    finally:
        connection.close()
    raw = b"".join(chunks)
    header, separator, body = raw.partition(b"\r\n\r\n")
    if not separator:
        raise ValueError("invalid Docker response")
    status_line = header.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    parts = status_line.split()
    if len(parts) < 2 or not parts[1].isdigit():
        raise ValueError("invalid Docker response")
    status = int(parts[1])
    if status < 200 or status >= 300:
        error = RuntimeError("Docker API returned an error")
        error.http_status = status
        raise error
    headers = header.decode("iso-8859-1", errors="replace").lower()
    if "transfer-encoding: chunked" in headers:
        decoded = []
        position = 0
        while True:
            end = body.find(b"\r\n", position)
            if end < 0:
                raise ValueError("invalid Docker response")
            size = int(body[position:end].split(b";", 1)[0], 16)
            position = end + 2
            if size == 0:
                break
            decoded.append(body[position:position + size])
            position += size + 2
        body = b"".join(decoded)
    return json.loads(body.decode("utf-8"))


def collect_docker(
    socket_path="/var/run/docker.sock",
    container_limit=0,
    request_func=None,
    now=None,
):
    request = request_func or (lambda path: _docker_request(socket_path, path))
    try:
        rows = request("/containers/json?all=1")
        if not isinstance(rows, list):
            raise ValueError("Docker response is not a list")
    except Exception as exc:
        status = getattr(exc, "http_status", None)
        return {
            "running": 0,
            "total": 0,
            "limit": min(max(0, int(container_limit or 0)), MAX_DOCKER_CONTAINERS),
            "truncated": False,
            "containers": [],
            "updated_at": None,
            "stale": True,
            "error": _error(
                "docker_unavailable",
                "Docker data is unavailable",
                "docker-collector",
                True,
                status if isinstance(status, int) and 100 <= status <= 599 else None,
            ),
        }

    configured_limit = min(max(0, int(container_limit or 0)), MAX_DOCKER_CONTAINERS)
    if len(rows) > MAX_DOCKER_COUNT:
        return {
            "running": 0,
            "total": 0,
            "limit": configured_limit,
            "truncated": False,
            "containers": [],
            "updated_at": None,
            "stale": True,
            "error": _error(
                "docker_response_too_large",
                "Docker data exceeds the allowed size",
                "docker-collector",
                False,
            ),
        }
    effective_limit = configured_limit or MAX_DOCKER_CONTAINERS
    selected = rows[:effective_limit]
    containers = []
    for row in selected:
        if not isinstance(row, dict):
            continue
        names = ", ".join(str(name).lstrip("/") for name in (row.get("Names") or []))
        containers.append(
            {
                "names": _truncate(names, MAX_DOCKER_NAME_LENGTH),
                "image": _truncate(row.get("Image"), MAX_DOCKER_IMAGE_LENGTH),
                "status": _truncate(row.get("Status"), MAX_DOCKER_STATUS_LENGTH),
                "ports": _truncate(_format_ports(row.get("Ports")), MAX_DOCKER_PORTS_LENGTH),
            }
        )
    total = len(rows)
    return {
        "running": sum(1 for row in rows if isinstance(row, dict) and row.get("State") == "running"),
        "total": total,
        "limit": configured_limit,
        "truncated": len(containers) < total,
        "containers": containers,
        "updated_at": _utc_timestamp(now),
        "stale": False,
        "error": None,
    }


def atomic_write_json(path, payload):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".snapshot-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class HostExtensionCollector(object):
    def __init__(
        self,
        host_os_release_file=None,
        hwmon_root=None,
        smart_device=None,
        docker_socket=None,
        hardware_interval=None,
        docker_interval=None,
        docker_container_limit=None,
        hermes_status_file=None,
        hermes_snapshot_interval=None,
        status_dir=None,
        command_runner=None,
        docker_request=None,
    ):
        self.host_os_release_file = host_os_release_file or os.getenv(
            "HOST_OS_RELEASE_FILE", "/host/etc/os-release"
        )
        self.hwmon_root = hwmon_root or os.getenv("HWMON_ROOT", "/sys/class/hwmon")
        self.smart_device = smart_device or os.getenv("SMART_DEVICE", "auto")
        self.docker_socket = docker_socket or os.getenv(
            "DOCKER_SOCKET", "/var/run/docker.sock"
        )
        self.hardware_interval = hardware_interval or _env_int("HARDWARE_INTERVAL", 600)
        self.docker_interval = docker_interval or _env_int("DOCKER_INTERVAL", 60)
        if docker_container_limit is None:
            docker_container_limit = _env_int("DOCKER_CONTAINER_LIMIT", 0, 0)
        self.docker_container_limit = min(max(0, docker_container_limit), MAX_DOCKER_CONTAINERS)
        self.hermes_status_file = hermes_status_file or os.getenv(
            "HERMES_STATUS_FILE", "/var/lib/serverstatus-client/hermes/hermes.json"
        )
        self.hermes_snapshot_interval = hermes_snapshot_interval or _env_int(
            "HERMES_SNAPSHOT_INTERVAL", 10
        )
        self.status_dir = status_dir if status_dir is not None else os.getenv(
            "CLIENT_STATUS_DIR", "/var/lib/serverstatus-client"
        )
        self.command_runner = command_runner
        self.docker_request = docker_request
        self.host_os, os_error = collect_host_os(self.host_os_release_file)
        self.cpu_model, cpu_error = collect_cpu_model(command_runner)
        self.identity_errors = [item for item in (os_error, cpu_error) if item]
        self._hardware = not_reported_hardware()
        self._docker = not_reported_docker()
        self._hermes = not_reported_hermes()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._started = False

    def _store(self, domain, payload):
        with self._lock:
            setattr(self, "_" + domain, copy.deepcopy(payload))
        if self.status_dir:
            try:
                atomic_write_json(os.path.join(self.status_dir, domain + ".json"), payload)
            except OSError:
                pass

    def collect_hardware_once(self):
        try:
            payload = collect_hardware(
                self.cpu_model,
                self.identity_errors,
                self.hwmon_root,
                self.smart_device,
                self.command_runner,
            )
        except Exception:
            payload = not_reported_hardware()
            payload["error"] = _error(
                "source_error",
                "Extension data is unavailable",
                "host-collector",
                True,
            )
        self._store("hardware", payload)
        return payload

    def collect_docker_once(self):
        try:
            payload = collect_docker(
                self.docker_socket,
                self.docker_container_limit,
                self.docker_request,
            )
        except Exception:
            payload = not_reported_docker()
            payload["error"] = _error(
                "source_error",
                "Extension data is unavailable",
                "docker-collector",
                True,
            )
        self._store("docker", payload)
        return payload

    def collect_hermes_once(self):
        payload = read_hermes_snapshot(self.hermes_status_file)
        self._store("hermes", payload)
        return payload

    def _run_periodically(self, function, interval):
        while not self._stop.is_set():
            try:
                function()
            except Exception:
                pass
            self._stop.wait(interval)

    def start(self):
        if self._started:
            return
        self._started = True
        for function, interval, name in (
            (self.collect_hardware_once, self.hardware_interval, "hardware-collector"),
            (self.collect_docker_once, self.docker_interval, "docker-collector"),
            (self.collect_hermes_once, self.hermes_snapshot_interval, "hermes-snapshot-reader"),
        ):
            thread = threading.Thread(
                target=self._run_periodically,
                args=(function, interval),
                name=name,
            )
            thread.daemon = True
            thread.start()

    def stop(self):
        self._stop.set()

    def extension_payload(self):
        with self._lock:
            hardware = copy.deepcopy(self._hardware)
            docker_stats = copy.deepcopy(self._docker)
            hermes = copy.deepcopy(self._hermes)
        return {
            "extension_version": EXTENSION_VERSION,
            "hardware": hardware,
            "docker": docker_stats,
            "hermes": hermes,
        }


def add_extension_payload(update, collector):
    try:
        update.update(collector.extension_payload())
    except Exception:
        update.update(
            {
                "extension_version": EXTENSION_VERSION,
                "hardware": not_reported_hardware(),
                "docker": not_reported_docker(),
                "hermes": not_reported_hermes(),
            }
        )
    return update
