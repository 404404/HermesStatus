"""Strict, file-backed UniFi hardware capability catalog.

Collection-target profiles live in ``unifi_profiles``.  This catalog is the
single source for hardware facts that are shared by gateways, switches and
APs.  Runtime identifiers are intentionally exact-match only: display names,
array position and management IP are never model identity evidence.
"""
from __future__ import annotations

import json
from pathlib import Path


MODEL_TYPES = {"gateway", "switch", "ap"}
CONNECTORS = {"rj45", "sfp", "sfp_plus", "sfp28", "other"}
IDENTIFIER_KINDS = {"api_model", "sysid", "ssh_model"}
PROVENANCE = {"qualified_controller", "qualified_ssh", "authoritative_documentation", "qualified_fixture"}
MODEL_DIRECTORY = Path(__file__).with_name("unifi_models")


class ModelCatalogError(ValueError):
    pass


def _bounded_text(value, field, maximum=128):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ModelCatalogError(f"invalid {field}")
    return value.strip()


def _positive_number(value, field, maximum=1000000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 or value > maximum:
        raise ModelCatalogError(f"invalid {field}")
    return value


def _nullable_positive_number(value, field, maximum=1000000):
    if value is None:
        return
    _positive_number(value, field, maximum)


def _validate_aliases(model):
    aliases = model.get("runtime_aliases")
    if not isinstance(aliases, dict) or set(aliases) != IDENTIFIER_KINDS:
        raise ModelCatalogError("invalid runtime_aliases")
    seen = set()
    for kind, entries in aliases.items():
        if not isinstance(entries, list) or len(entries) > 16:
            raise ModelCatalogError(f"invalid {kind} aliases")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"value", "provenance", "runtime_verified", "evidence"}:
                raise ModelCatalogError(f"invalid {kind} alias")
            value = _bounded_text(entry["value"], f"{kind}.value")
            provenance = _bounded_text(entry["provenance"], f"{kind}.provenance", 64)
            if provenance not in PROVENANCE or not isinstance(entry["runtime_verified"], bool):
                raise ModelCatalogError(f"invalid {kind} alias state")
            evidence = _bounded_text(entry["evidence"], f"{kind}.evidence", 256)
            key = (kind, value)
            if key in seen:
                raise ModelCatalogError("duplicate runtime alias")
            seen.add(key)
            if entry["runtime_verified"] and provenance not in {"qualified_controller", "qualified_ssh", "qualified_fixture"}:
                raise ModelCatalogError("documentation-only alias cannot be runtime verified")
    return seen


def _validate_ports(model):
    ports = model.get("ports")
    if not isinstance(ports, list) or len(ports) > 64:
        raise ModelCatalogError("invalid ports")
    seen = set()
    for port in ports:
        if not isinstance(port, dict):
            raise ModelCatalogError("invalid port")
        required = {"index", "label", "connector", "max_speed_mbps", "roles", "poe_in", "poe_out", "poe_standard", "poe_max_power_w", "combo_group"}
        if set(port) != required:
            raise ModelCatalogError("invalid port fields")
        index = port["index"]
        if not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= 65535 or index in seen:
            raise ModelCatalogError("invalid or duplicate port index")
        seen.add(index)
        _bounded_text(port["label"], "port.label")
        if port["connector"] not in CONNECTORS:
            raise ModelCatalogError("invalid port connector")
        _positive_number(port["max_speed_mbps"], "port.max_speed_mbps")
        roles = port["roles"]
        if not isinstance(roles, list) or not roles or any(role not in {"lan", "wan"} for role in roles) or len(set(roles)) != len(roles):
            raise ModelCatalogError("invalid port roles")
        if not isinstance(port["poe_in"], bool) or not isinstance(port["poe_out"], bool):
            raise ModelCatalogError("invalid port poe flags")
        standard = port["poe_standard"]
        if standard is not None and standard not in {"poe", "poe+", "poe++"}:
            raise ModelCatalogError("invalid port poe standard")
        _nullable_positive_number(port["poe_max_power_w"], "port.poe_max_power_w")
        combo = port["combo_group"]
        if combo is not None:
            _bounded_text(combo, "port.combo_group", 64)
    groups = {port["combo_group"] for port in ports if port["combo_group"] is not None}
    if any(sum(1 for port in ports if port["combo_group"] == group) < 2 for group in groups):
        raise ModelCatalogError("combo group must reference at least two ports")
    return seen


def _validate_capabilities(model):
    storage = model.get("storage")
    if not isinstance(storage, dict) or set(storage) != {"nvme", "sata_ssd", "tf"}:
        raise ModelCatalogError("invalid storage")
    for name, capability in storage.items():
        if not isinstance(capability, dict) or set(capability) != {"supported", "present", "capacity_bytes"}:
            raise ModelCatalogError(f"invalid storage capability: {name}")
        if capability["supported"] not in {True, False, "unknown"} or capability["present"] not in {"present", "not_populated", "unknown"}:
            raise ModelCatalogError(f"invalid storage capability: {name}")
        capacity = capability["capacity_bytes"]
        if capacity is not None and (not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 0):
            raise ModelCatalogError(f"invalid storage capacity: {name}")
    power = model.get("power")
    if not isinstance(power, dict) or set(power) != {"psu_slots", "max_power_w"}:
        raise ModelCatalogError("invalid power")
    if not isinstance(power["psu_slots"], int) or isinstance(power["psu_slots"], bool) or not 0 <= power["psu_slots"] <= 4:
        raise ModelCatalogError("invalid power psu_slots")
    _nullable_positive_number(power["max_power_w"], "power.max_power_w")
    return storage, power


def validate_model(model):
    if not isinstance(model, dict):
        raise ModelCatalogError("model must be an object")
    required = {"schema_version", "canonical_sku", "display_name", "device_type", "runtime_aliases", "ports", "storage", "power"}
    if set(model) != required or model["schema_version"] != 1:
        raise ModelCatalogError("unexpected or missing model fields")
    _bounded_text(model["canonical_sku"], "canonical_sku")
    _bounded_text(model["display_name"], "display_name")
    if model["device_type"] not in MODEL_TYPES:
        raise ModelCatalogError("invalid device_type")
    _validate_aliases(model)
    _validate_ports(model)
    _validate_capabilities(model)
    return model


def load_catalog(directory=MODEL_DIRECTORY):
    directory = Path(directory)
    models = {}
    owners = {}
    for path in sorted(directory.glob("*.json")):
        if path.name == "model.schema.json":
            continue
        try:
            model = validate_model(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ModelCatalogError) as exc:
            raise ModelCatalogError(f"invalid model file {path.name}") from exc
        sku = model["canonical_sku"]
        if sku in models or sku in owners:
            raise ModelCatalogError("duplicate canonical model ownership")
        models[sku] = model
        owners[sku] = path.name
    if not models:
        raise ModelCatalogError("model catalog is empty")
    alias_owners = {}
    canonical_skus = set(models)
    for sku, model in models.items():
        alias_owners[sku] = sku
        for kind, entries in model["runtime_aliases"].items():
            for entry in entries:
                if not entry["runtime_verified"]:
                    continue
                value = entry["value"]
                if value in canonical_skus and value != sku:
                    raise ModelCatalogError("runtime alias collides with canonical model")
                key = (kind, value)
                if key in alias_owners and alias_owners[key] != sku:
                    raise ModelCatalogError("duplicate verified runtime alias ownership")
                alias_owners[key] = sku
    return models


def resolve_model(catalog, value, *, kind="api_model"):
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    direct = catalog.get(value)
    if direct is not None:
        return direct
    if kind not in IDENTIFIER_KINDS:
        return None
    for model in catalog.values():
        for alias in model["runtime_aliases"][kind]:
            if alias["runtime_verified"] and alias["value"] == value:
                return model
    return None
