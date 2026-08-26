"""Profile-driven normalization of fixed raw observations."""
from copy import deepcopy
from datetime import datetime, timezone

def _parse_cpu(line):
    fields = line.split()
    if not fields or fields[0] != "cpu" or len(fields) < 5:
        raise ValueError("invalid /proc/stat cpu line")
    values = [int(v) for v in fields[1:]]
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return total, idle

def _parse_mem(mem):
    required = {"MemTotal", "MemAvailable", "MemFree", "Buffers", "Cached", "SwapTotal", "SwapFree"}
    if set(mem) != required:
        raise ValueError("invalid meminfo keys")
    values = {key: int(value) * 1024 for key, value in mem.items()}
    if values["MemTotal"] <= 0 or values["MemAvailable"] > values["MemTotal"]:
        raise ValueError("invalid meminfo values")
    return values

def _fan_output(profile, raw_fans):
    supported = {f["id"]: f for f in profile["fans"]["channels"]}
    output, ignored = [], []
    for fan_id, rpm in raw_fans.items():
        capability = supported.get(fan_id)
        if capability and capability["present"] == "not_populated":
            ignored.append({"id": fan_id, "reason": "profile_not_populated", "rpm": rpm})
        elif capability:
            output.append({"id": fan_id, "rpm": rpm, "supported": True, "present": capability["present"], "health": "unknown" if capability["present"] == "unknown" else "not_evaluated"})
    return output, ignored

def normalize(profile, raw, previous=None):
    now = raw.get("collected_at") or datetime.now(timezone.utc).isoformat()
    target_id = raw.get("target_id")
    if not raw.get("transport", {}).get("ok"):
        return {"target_id": target_id, "profile_id": profile["profile_id"], "platform": profile["platform"], "system": None, "fans": [], "power_supplies": [], "diagnostics": {}, "updated_at": now, "stale": True, "error": {"code": "ssh_transport_failure"}, "previous_observation": deepcopy(previous) if previous else None}
    generic = raw["generic"]
    mem = _parse_mem(generic["meminfo"])
    total, idle = _parse_cpu(generic["proc_stat_cpu"])
    previous_cpu = previous.get("_cpu_baseline") if previous else None
    cpu_pct, cpu_reason = None, "insufficient_delta"
    if previous_cpu and total > previous_cpu["total"] and idle >= previous_cpu["idle"]:
        cpu_pct = round((1 - (idle - previous_cpu["idle"]) / (total - previous_cpu["total"])) * 100, 2)
        cpu_reason = None
    uptime = float(generic["uptime_raw"].split()[0])
    load = [float(v) for v in generic["loadavg_raw"].split()[:3]]
    if len(load) != 3:
        raise ValueError("invalid loadavg")
    fans, ignored = _fan_output(profile, raw.get("diagnostics", {}).get("fans", {}))
    diagnostics = deepcopy(raw.get("diagnostics", {}))
    diagnostics["ignored_observations"] = ignored
    diagnostics["nvme"] = deepcopy(profile["storage"]["nvme"])
    return {
        "target_id": target_id, "profile_id": profile["profile_id"], "platform": profile["platform"],
        "system": {"cpu_usage_pct": cpu_pct, "cpu_usage_reason": cpu_reason, "cpu_temperature_c": float(generic["cpu_temperature_raw"]), "memory": {"total_bytes": mem["MemTotal"], "available_bytes": mem["MemAvailable"], "free_bytes": mem["MemFree"], "buffers_bytes": mem["Buffers"], "cached_bytes": mem["Cached"], "swap_total_bytes": mem["SwapTotal"], "swap_free_bytes": mem["SwapFree"], "used_bytes": mem["MemTotal"] - mem["MemAvailable"], "used_pct": round((mem["MemTotal"] - mem["MemAvailable"]) / mem["MemTotal"] * 100, 2)}, "uptime_seconds": uptime, "load_average": {"1m": load[0], "5m": load[1], "15m": load[2]}},
        "fans": fans, "power_supplies": [], "diagnostics": diagnostics, "updated_at": now, "stale": False, "error": None, "_cpu_baseline": {"total": total, "idle": idle}
    }
