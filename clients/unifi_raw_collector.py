"""Strict parsing for the fixed UniFi prototype collection scripts."""
import json
import math
import re
from datetime import datetime, timezone
from unifi_ssh_transport import collect_core, collect_diagnostics, collect_udw_filesystem, TransportError

MARKERS = ("__HS_CPU_TEMP__", "__HS_PROC_STAT__", "__HS_MEMINFO__", "__HS_UPTIME__", "__HS_LOADAVG__", "__HS_END__")
FAN_INPUT_RE = re.compile(r"^fan([1-9][0-9]*)_input$")
FILESYSTEM_MARKERS = ("__HS_UDW_SSD_FILESYSTEM__", "__HS_END__")

def _sections(text):
    lines = text.splitlines()
    found = {marker: [] for marker in MARKERS}
    current = None
    for line in lines:
        if line in found:
            current = line
        elif current:
            found[current].append(line)
    if any(marker not in lines for marker in MARKERS) or lines[-1:] != ["__HS_END__"]:
        raise ValueError("invalid fixed SSH section framing")
    return found

def parse_core(text, target_id="ucg-max", profile_id="ucg-max"):
    sections = _sections(text)
    cpu_temp = sections["__HS_CPU_TEMP__"]
    proc_stat = sections["__HS_PROC_STAT__"]
    uptime = sections["__HS_UPTIME__"]
    loadavg = sections["__HS_LOADAVG__"]
    if len(cpu_temp) != 1 or len(proc_stat) != 1 or len(uptime) != 1 or len(loadavg) != 1:
        raise ValueError("invalid core section cardinality")
    meminfo = {}
    for line in sections["__HS_MEMINFO__"]:
        fields = line.replace(":", "").split()
        if len(fields) != 3 or fields[2] != "kB":
            raise ValueError("invalid meminfo line")
        meminfo[fields[0]] = fields[1]
    return {"target_id": target_id, "profile_id": profile_id, "collected_at": datetime.now(timezone.utc).isoformat(), "generic": {"cpu_temperature_raw": cpu_temp[0].strip().replace("C", "").replace("°", ""), "proc_stat_cpu": proc_stat[0], "meminfo": meminfo, "uptime_raw": uptime[0], "loadavg_raw": loadavg[0]}, "diagnostics": {}, "transport": {"ok": True, "error": None}}

def _sensor_fans(text, expected_name=None):
    """Extract only driver-labelled fan*_input RPM observations from sensors -j."""
    if not isinstance(text, str) or not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    result = {}
    for chip_name in sorted(payload):
        if expected_name and expected_name.lower() not in str(chip_name).lower():
            continue
        chip = payload.get(chip_name)
        if not isinstance(chip, dict):
            continue
        for channel_name in sorted(chip):
            channel = chip.get(channel_name)
            if not isinstance(channel, dict):
                continue
            for field_name in sorted(channel):
                match = FAN_INPUT_RE.fullmatch(str(field_name))
                if not match:
                    continue
                value = channel.get(field_name)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                if not math.isfinite(value) or value < 0 or not float(value).is_integer():
                    continue
                fan_id = "fan" + match.group(1)
                result.setdefault(fan_id, int(value))
                if len(result) >= 16:
                    return result
    return result


def parse_diagnostics(text, expected_hwmon_name=None):
    lines = text.splitlines()
    if "__HS_THERMAL__" not in lines or "__HS_HWMON__" not in lines or "__HS_HW_CACHE__" not in lines or lines[-1:] != ["__HS_END__"]:
        raise ValueError("invalid diagnostics framing")
    thermal_start, hwmon_start, cache_start = lines.index("__HS_THERMAL__"), lines.index("__HS_HWMON__"), lines.index("__HS_HW_CACHE__")
    zones = []
    for line in lines[thermal_start + 1:hwmon_start]:
        fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
        if {"zone", "type", "temp"} <= set(fields):
            zones.append(fields)
    cache_text = "\n".join(lines[cache_start + 1:-1])
    cache = None
    cache_status = "unavailable"
    if cache_text.strip():
        try:
            parsed = json.loads(cache_text)
        except (TypeError, ValueError):
            cache_status = "invalid"
        else:
            if isinstance(parsed, (dict, list)):
                cache = parsed
                cache_status = "available"
            else:
                cache_status = "invalid"
    hwmon_json = "\n".join(lines[hwmon_start + 1:cache_start])
    return {"thermal_zones": zones, "hwmon_json_available": bool(hwmon_json.strip()), "fans": _sensor_fans(hwmon_json, expected_hwmon_name), "hardware_cache": cache, "hardware_cache_status": cache_status}


def parse_udw_filesystem(text):
    """Parse only the fixed UDW /ssd1 df observation."""
    if not isinstance(text, str) or len(text) > 32768:
        raise ValueError("invalid filesystem framing")
    lines = text.splitlines()
    if FILESYSTEM_MARKERS[0] not in lines or lines[-1:] != [FILESYSTEM_MARKERS[1]]:
        raise ValueError("invalid filesystem framing")
    start = lines.index(FILESYSTEM_MARKERS[0]) + 1
    body = lines[start:-1]
    if body == ["__HS_DF_UNAVAILABLE__"]:
        return {"status": "unavailable", "mountpoint": "/ssd1"}
    if len(body) != 2:
        raise ValueError("invalid filesystem row count")
    header, row = body
    if len(header.split()) < 6:
        raise ValueError("invalid filesystem header")
    fields = row.split()
    if len(fields) != 6 or fields[5] != "/ssd1":
        raise ValueError("invalid filesystem row")
    device, total, used, available, usage, mountpoint = fields
    if not re.fullmatch(r"/(?:[A-Za-z0-9._+-]+/)*[A-Za-z0-9._+-]+", device):
        raise ValueError("invalid filesystem device")
    if not all(re.fullmatch(r"[0-9]+", value) for value in (total, used, available)):
        raise ValueError("invalid filesystem numbers")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%", usage):
        raise ValueError("invalid filesystem percentage")
    total_value, used_value, available_value = (int(value) for value in (total, used, available))
    usage_value = float(usage[:-1])
    if any(value < 0 or value > (1 << 50) for value in (total_value, used_value, available_value)):
        raise ValueError("filesystem number out of bounds")
    if used_value > total_value or available_value > total_value or not math.isfinite(usage_value) or not 0 <= usage_value <= 100:
        raise ValueError("invalid filesystem relations")
    return {
        "status": "available",
        "mountpoint": mountpoint,
        "device": device,
        "filesystem_total_bytes": total_value,
        "used_bytes": used_value,
        "available_bytes": available_value,
        "usage_percent": usage_value,
    }

class RawCollector:
    def __init__(self, config, target_id=None, hwmon_expected_name=None):
        self.config = config
        self.target_id = target_id or config.profile_id
        self.profile_id = config.profile_id
        self.hwmon_expected_name = hwmon_expected_name

    def collect(self):
        try:
            return parse_core(collect_core(self.config), self.target_id, self.profile_id)
        except TransportError as exc:
            return {"target_id": self.target_id, "profile_id": self.profile_id, "collected_at": datetime.now(timezone.utc).isoformat(), "transport": {"ok": False, "error": str(exc)}}
        except ValueError:
            return {"target_id": self.target_id, "profile_id": self.profile_id, "collected_at": datetime.now(timezone.utc).isoformat(), "transport": {"ok": False, "error": "parse_failure"}}

    def diagnostics(self):
        try:
            return parse_diagnostics(collect_diagnostics(self.config), self.hwmon_expected_name)
        except (TransportError, ValueError):
            return {"collection_status": "unavailable"}

    def filesystem(self):
        if self.profile_id != "udw":
            return {"status": "not_configured", "mountpoint": "/ssd1"}
        try:
            return parse_udw_filesystem(collect_udw_filesystem(self.config))
        except (TransportError, ValueError):
            return {"status": "unavailable", "mountpoint": "/ssd1"}
