"""Profile-driven, bounded UniFi normalization for Device v2 telemetry."""
from datetime import datetime, timezone


def _timestamp(raw):
    return raw.get("collected_at") or datetime.now(timezone.utc).isoformat()


def _error(code):
    messages = {
        "host_key_configuration": "UniFi SSH host-key configuration is unavailable",
        "host_key_failure": "UniFi SSH host-key verification failed",
        "ssh_auth_failure": "UniFi SSH authentication failed",
        "ssh_timeout": "UniFi SSH timed out",
        "parse_failure": "UniFi telemetry parsing failed",
    }
    return {
        "code": code if code in messages else "ssh_transport_failure",
        "message": messages.get(code, "UniFi SSH transport is unavailable"),
        "source": "unifi",
        "retryable": code not in {"host_key_configuration", "host_key_failure", "ssh_auth_failure"},
        "http_status": None,
    }


def _parse_cpu(line):
    fields = line.split()
    if not fields or fields[0] != "cpu" or len(fields) < 5:
        raise ValueError("invalid /proc/stat cpu line")
    try:
        values = [int(value) for value in fields[1:]]
    except ValueError as exc:
        raise ValueError("invalid /proc/stat cpu line") from exc
    if any(value < 0 for value in values):
        raise ValueError("invalid /proc/stat cpu line")
    return sum(values), values[3] + (values[4] if len(values) > 4 else 0)


def _parse_mem(mem):
    required = {"MemTotal", "MemFree", "Buffers", "Cached", "SwapTotal", "SwapFree"}
    if not isinstance(mem, dict) or not required <= set(mem):
        raise ValueError("invalid meminfo keys")
    try:
        values = {key: int(value) * 1024 for key, value in mem.items()}
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid meminfo values") from exc
    if any(value < 0 for value in values.values()) or values["MemTotal"] <= 0:
        raise ValueError("invalid meminfo values")
    available = values.get("MemAvailable")
    source = "mem_available"
    if available is None:
        available = values["MemFree"] + values["Buffers"] + values["Cached"]
        source = "fallback_memfree_buffers_cached"
    if available < 0 or available > values["MemTotal"]:
        raise ValueError("invalid meminfo values")
    values["MemAvailable"] = available
    values["AvailableSource"] = source
    return values


def _cpu_delta(total, idle, previous):
    baseline = previous.get("_cpu_baseline") if previous else None
    if not baseline:
        return None, "insufficient_delta"
    old_total, old_idle = baseline.get("total"), baseline.get("idle")
    if not isinstance(old_total, int) or not isinstance(old_idle, int):
        return None, "invalid_sample"
    if total < old_total or idle < old_idle:
        return None, "counter_reset"
    delta_total, delta_idle = total - old_total, idle - old_idle
    if delta_total == 0:
        return None, "zero_delta"
    if delta_idle > delta_total:
        return None, "invalid_sample"
    return round((delta_total - delta_idle) / delta_total * 100, 2), None


def _state_for_rpm(rpm):
    return "observed_zero_rpm" if rpm == 0 else "observed"


def _cache_section(cache, names):
    if not isinstance(cache, dict):
        return None
    for name in names:
        value = cache.get(name)
        if isinstance(value, (dict, list)):
            return value
    for value in cache.values():
        if isinstance(value, dict):
            nested = _cache_section(value, names)
            if nested is not None:
                return nested
    return None


def _cache_fans(cache):
    section = _cache_section(cache, ("fans", "fan"))
    if isinstance(section, dict):
        result = {}
        for key, value in section.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[str(key)] = value
            elif isinstance(value, dict):
                rpm = value.get("rpm", value.get("speed"))
                if isinstance(rpm, (int, float)) and not isinstance(rpm, bool):
                    result[str(value.get("id", key))] = rpm
        return result
    if isinstance(section, list):
        result = {}
        for value in section[:16]:
            if isinstance(value, dict):
                rpm = value.get("rpm", value.get("speed"))
                ident = value.get("id", value.get("name"))
                if isinstance(ident, str) and isinstance(rpm, (int, float)) and not isinstance(rpm, bool):
                    result[ident] = rpm
        return result
    result = {}
    def visit(value, depth=0):
        if depth > 4 or len(result) >= 16:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                lowered = str(key).lower()
                if lowered.startswith("fan") and lowered[3:].isdigit():
                    if isinstance(child, (int, float)) and not isinstance(child, bool):
                        result[lowered] = child
                    elif isinstance(child, dict):
                        rpm = child.get("rpm", child.get("speed"))
                        if isinstance(rpm, (int, float)) and not isinstance(rpm, bool):
                            result[lowered] = rpm
                visit(child, depth + 1)
        elif isinstance(value, list):
            for child in value[:16]:
                visit(child, depth + 1)
    visit(cache)
    return result


def _cache_records(cache, names):
    section = _cache_section(cache, names)
    if isinstance(section, list):
        return [item for item in section[:8] if isinstance(item, dict)]
    if isinstance(section, dict):
        result = []
        for key, value in section.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("id", str(key))
                result.append(item)
        return result[:8]
    return []


def _fans(profile, raw_fans, hardware_cache=None):
    observed = raw_fans if isinstance(raw_fans, dict) else {}
    if not observed and hardware_cache is not None:
        observed = _cache_fans(hardware_cache)
    output, ignored = [], []
    for capability in profile["fans"]["channels"]:
        fan_id = capability["id"]
        present = capability["present"]
        if present == "not_populated":
            if fan_id in observed:
                ignored.append({"id": fan_id, "reason": "profile_not_populated"})
            continue
        rpm = observed.get(fan_id)
        if isinstance(rpm, bool) or not isinstance(rpm, int) or rpm < 0:
            rpm = None
        output.append({
            "id": fan_id,
            "supported": "supported" if capability["supported"] else "unsupported",
            "present": present,
            "observed": rpm is not None,
            "rpm": rpm,
            "state": _state_for_rpm(rpm) if rpm is not None else "not_observed",
            "error": None,
        })
    return output, ignored


def _power(profile, hardware_cache=None):
    slots = profile["power"]["psu_slots"]
    presence = profile["power"]["presence"]
    # `dynamic` is a model capability, not a runtime presence observation.
    # Preserve that uncertainty as `unknown` until a qualified sensor mapping
    # proves an individual PSU slot is present or absent.
    present = "unknown" if presence == "dynamic" else presence
    result = [{
        "id": f"psu{index}", "supported": "supported", "present": present,
        "observed": False, "state": "not_observed", "error": None,
    } for index in range(1, slots + 1)]
    records = _cache_records(hardware_cache, ("power_supplies", "psus", "power_supply")) if hardware_cache else []
    for record in records:
        ident = str(record.get("id", record.get("slot", "")))
        index = next((i for i in range(len(result)) if result[i]["id"].lower() == ident.lower() or str(i + 1) == ident), None)
        if index is None:
            continue
        item = result[index]
        if record.get("present") in {True, False}:
            item["present"] = "present" if record["present"] else "not_present"
        watts = record.get("power_w", record.get("power"))
        fan_rpm = record.get("fan_rpm", record.get("rpm"))
        if isinstance(watts, (int, float)) and not isinstance(watts, bool) and watts >= 0:
            item["power_w"] = watts
        if isinstance(fan_rpm, (int, float)) and not isinstance(fan_rpm, bool) and fan_rpm >= 0:
            item["fan_rpm"] = int(fan_rpm)
        if item["present"] == "present" and ("power_w" in item or "fan_rpm" in item):
            item["observed"] = True
            item["state"] = "observed"
    return result


def _storage(profile, hardware_cache=None):
    result = {}
    for name, capability in profile["storage"].items():
        supported = capability["supported"]
        result[name] = {
            "supported": "supported" if supported is True else "unsupported" if supported is False else "unknown",
            "present": "not_present" if capability["present"] == "not_populated" else capability["present"],
            "observed": capability["observed"] is True,
            "capacity_bytes": capability["capacity_bytes"],
        }
    records = _cache_records(hardware_cache, ("storage", "storages", "disks", "block_devices")) if hardware_cache else []
    aliases = {"sata_ssd": {"sata_ssd", "sata", "ssd"}, "tf": {"tf", "sd", "mmc", "tf_card"}, "nvme": {"nvme"}}
    for record in records:
        category = str(record.get("category", record.get("type", record.get("id", "")))).lower().replace("-", "_")
        name = next((key for key, values in aliases.items() if category in values or any(value in category for value in values)), None)
        if name is None or name not in result:
            continue
        item = result[name]
        if record.get("present") in {True, False}:
            item["present"] = "present" if record["present"] else "not_present"
        for output, keys in (("capacity_bytes", ("capacity_bytes", "total_bytes", "size_bytes")), ("used_bytes", ("used_bytes", "used")), ("available_bytes", ("available_bytes", "free_bytes", "available")), ("usage_percent", ("usage_percent", "used_percent", "usage_pct"))):
            value = next((record.get(key) for key in keys if record.get(key) is not None), None)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                item[output] = value
        if item.get("present") == "present" and item.get("capacity_bytes") is not None:
            item["observed"] = True
    return result


def _api_observation(raw, previous=None):
    value = raw.get("api")
    if isinstance(value, dict):
        return value
    if isinstance(previous, dict) and isinstance(previous.get("api"), dict):
        return previous["api"]
    return {"enabled": False, "status": "disabled", "last_attempt": None, "last_success": None, "endpoints": [], "summary": None, "error": None}


def normalize(profile, raw, previous=None):
    now = _timestamp(raw)
    transport = raw.get("transport", {})
    if not transport.get("ok"):
        return {
            "profile": profile["profile_id"],
            "transport": {"status": "unavailable", "last_attempt": now,
                          "last_success": previous.get("updated_at") if previous else None},
            "api": _api_observation(raw, previous),
            "system": previous.get("system") if previous else None,
            "fans": previous.get("fans", []) if previous else [],
            "power_supplies": previous.get("power_supplies", _power(profile)) if previous else _power(profile),
            "storage": previous.get("storage", _storage(profile)) if previous else _storage(profile),
            "diagnostics": previous.get("diagnostics", {"collection_status": "unavailable", "ignored_observations": []}) if previous else {"collection_status": "unavailable", "ignored_observations": []},
            "updated_at": previous.get("updated_at") if previous else None,
            "stale": True,
            "error": _error(transport.get("error")),
        }
    generic = raw["generic"]
    mem = _parse_mem(generic["meminfo"])
    total, idle = _parse_cpu(generic["proc_stat_cpu"])
    cpu_pct, cpu_reason = _cpu_delta(total, idle, previous)
    try:
        temperature = float(generic["cpu_temperature_raw"])
        uptime = float(generic["uptime_raw"].split()[0])
        load = [float(value) for value in generic["loadavg_raw"].split()[:3]]
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("invalid generic observation") from exc
    if len(load) != 3 or temperature < -100 or temperature > 250 or uptime < 0 or any(value < 0 for value in load):
        raise ValueError("invalid generic observation")
    diagnostics_raw = raw.get("diagnostics", {}) if isinstance(raw.get("diagnostics", {}), dict) else {}
    hardware_cache = diagnostics_raw.get("hardware_cache") if isinstance(diagnostics_raw.get("hardware_cache"), (dict, list)) else None
    fans, ignored = _fans(profile, diagnostics_raw.get("fans", {}), hardware_cache)
    diagnostic_status = "available" if raw.get("diagnostics") else "not_collected"
    if raw.get("diagnostics", {}).get("collection_status") == "unavailable":
        diagnostic_status = "unavailable"
    return {
        "profile": profile["profile_id"],
        "transport": {"status": "available", "last_attempt": now, "last_success": now},
        "api": _api_observation(raw, previous),
        "system": {
            "cpu_model": profile.get("cpu_model"),
            "cpu_usage_percent": cpu_pct,
            "cpu_usage_reason": cpu_reason,
            "cpu_temperature_c": temperature,
            "memory": {
                "total_bytes": mem["MemTotal"], "available_bytes": mem["MemAvailable"],
                "free_bytes": mem["MemFree"], "buffers_bytes": mem["Buffers"],
                "cached_bytes": mem["Cached"], "swap_total_bytes": mem["SwapTotal"],
                "swap_free_bytes": mem["SwapFree"], "used_bytes": mem["MemTotal"] - mem["MemAvailable"],
                "used_percent": round((mem["MemTotal"] - mem["MemAvailable"]) / mem["MemTotal"] * 100, 2),
                "available_source": mem["AvailableSource"],
            },
            "uptime_seconds": uptime,
            "load_average": {"one_minute": load[0], "five_minutes": load[1], "fifteen_minutes": load[2]},
        },
        "fans": fans,
        "power_supplies": _power(profile, hardware_cache),
        "storage": _storage(profile, hardware_cache),
        "diagnostics": {"collection_status": diagnostic_status, "ignored_observations": ignored, "hardware_cache_status": diagnostics_raw.get("hardware_cache_status", "unavailable")},
        "updated_at": now,
        "stale": False,
        "error": None,
        "_cpu_baseline": {"total": total, "idle": idle},
    }
