"""Strict parsing for the fixed UniFi prototype collection scripts."""
import json
from datetime import datetime, timezone
from unifi_ssh_transport import collect_core, collect_diagnostics, TransportError

MARKERS = ("__HS_CPU_TEMP__", "__HS_PROC_STAT__", "__HS_MEMINFO__", "__HS_UPTIME__", "__HS_LOADAVG__", "__HS_END__")

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

def parse_diagnostics(text):
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
    return {"thermal_zones": zones, "hwmon_json_available": bool("\n".join(lines[hwmon_start + 1:cache_start]).strip()), "hardware_cache": cache, "hardware_cache_status": cache_status}

class RawCollector:
    def __init__(self, config, target_id=None):
        self.config = config
        self.target_id = target_id or config.profile_id
        self.profile_id = config.profile_id

    def collect(self):
        try:
            return parse_core(collect_core(self.config), self.target_id, self.profile_id)
        except TransportError as exc:
            return {"target_id": self.target_id, "profile_id": self.profile_id, "collected_at": datetime.now(timezone.utc).isoformat(), "transport": {"ok": False, "error": str(exc)}}
        except ValueError:
            return {"target_id": self.target_id, "profile_id": self.profile_id, "collected_at": datetime.now(timezone.utc).isoformat(), "transport": {"ok": False, "error": "parse_failure"}}

    def diagnostics(self):
        try:
            return parse_diagnostics(collect_diagnostics(self.config))
        except (TransportError, ValueError):
            return {"collection_status": "unavailable"}
