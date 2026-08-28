"""Strict V1 profile loading without a third-party JSON-schema package."""
import json
from pathlib import Path
from unifi_source_registry import KNOWN_SOURCES, CORE_SOURCES

PRESENCE = {"present", "not_populated", "unknown", "dynamic"}
STORAGE_CAPABILITIES = {"nvme", "sata_ssd", "tf"}
REQUIRED_ROOT_KEYS = {"schema_version", "profile_id", "platform", "generic", "diagnostics", "fans", "power", "storage", "health_policy"}
OPTIONAL_ROOT_KEYS = {"cpu_model"}
GENERIC_KEYS = {"cpu_temperature", "cpu_usage", "memory", "uptime", "load_average"}

class ProfileError(ValueError):
    pass

def _require_source(node, name):
    if not isinstance(node, dict) or set(node) - {"source", "primary", "formula", "health_affecting", "zones", "expected_name"}:
        raise ProfileError(f"invalid source definition: {name}")
    source = node.get("source")
    if source not in KNOWN_SOURCES:
        raise ProfileError(f"unknown source: {source!r}")
    return source

def validate_profile(profile):
    if (not isinstance(profile, dict) or not REQUIRED_ROOT_KEYS <= set(profile)
            or set(profile) - REQUIRED_ROOT_KEYS - OPTIONAL_ROOT_KEYS):
        raise ProfileError("unexpected or missing root profile fields")
    if profile.get("schema_version") != 1:
        raise ProfileError("unsupported schema_version")
    profile_id = profile.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id or not all(c.islower() or c.isdigit() or c == "-" for c in profile_id):
        raise ProfileError("invalid profile_id")
    if profile.get("platform") != "unifi_console":
        raise ProfileError("unknown platform")
    if "cpu_model" in profile and (not isinstance(profile["cpu_model"], str) or not profile["cpu_model"].strip() or len(profile["cpu_model"]) > 128):
        raise ProfileError("invalid cpu_model")
    generic = profile["generic"]
    if not isinstance(generic, dict) or set(generic) != GENERIC_KEYS:
        raise ProfileError("invalid generic fields")
    for name, node in generic.items():
        if _require_source(node, name) not in CORE_SOURCES:
            raise ProfileError(f"non-core generic source: {name}")
    diagnostics = profile["diagnostics"]
    if not isinstance(diagnostics, dict):
        raise ProfileError("invalid diagnostics")
    for name, node in diagnostics.items():
        _require_source(node, name)
        if node.get("health_affecting") is not False:
            raise ProfileError("diagnostics must be non-health-affecting in V1")
    fans = profile["fans"]
    if not isinstance(fans, dict) or not isinstance(fans.get("channels"), list):
        raise ProfileError("invalid fans")
    physical_count = fans.get("physical_count")
    if physical_count is not None and (not isinstance(physical_count, int) or physical_count < 0):
        raise ProfileError("invalid physical_count")
    ids = set()
    for fan in fans["channels"]:
        if not isinstance(fan, dict) or set(fan) != {"id", "supported", "present"}:
            raise ProfileError("invalid fan")
        if not isinstance(fan["id"], str) or fan["id"] in ids:
            raise ProfileError("duplicate or invalid fan id")
        ids.add(fan["id"])
        if not isinstance(fan["supported"], bool) or fan["present"] not in PRESENCE:
            raise ProfileError("invalid fan capability")
    power = profile["power"]
    if not isinstance(power, dict) or set(power) != {"psu_slots", "presence", "sensor_mapping"} or not isinstance(power["psu_slots"], int) or power["psu_slots"] < 0 or power["presence"] not in PRESENCE or power["sensor_mapping"] not in {"unknown"}:
        raise ProfileError("invalid power")
    storage = profile["storage"]
    if not isinstance(storage, dict) or set(storage) != STORAGE_CAPABILITIES:
        raise ProfileError("invalid storage")
    for name, capability in storage.items():
        if not isinstance(capability, dict) or set(capability) != {"supported", "present", "observed", "capacity_bytes"}:
            raise ProfileError(f"invalid storage capability: {name}")
        if capability["supported"] not in {True, False, "unknown"} or capability["present"] not in PRESENCE or capability["observed"] not in {True, False, "unknown"}:
            raise ProfileError(f"invalid storage capability: {name}")
        capacity = capability["capacity_bytes"]
        if capacity is not None and (isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0):
            raise ProfileError(f"invalid storage capacity: {name}")
    policy = profile["health_policy"]
    if not isinstance(policy, dict) or set(policy) != {"optional_diagnostics_affect_health", "zero_rpm_is_failure_when_present"} or any(not isinstance(v, bool) for v in policy.values()):
        raise ProfileError("invalid health policy")
    return profile

def load_profile(directory, profile_id):
    if not isinstance(profile_id, str) or not profile_id or "/" in profile_id or ".." in profile_id:
        raise ProfileError("unknown_profile")
    path = Path(directory) / f"{profile_id}.json"
    if not path.is_file():
        raise ProfileError("unknown_profile")
    return validate_profile(json.loads(path.read_text(encoding="utf-8")))
