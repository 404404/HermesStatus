"""UniFi domain adapter for the HermesStatus host extension lifecycle."""
from __future__ import annotations

import copy
from pathlib import Path

from unifi_normalizer import normalize
from unifi_model_catalog import MODEL_DIRECTORY, load_catalog, project_static_capabilities, resolve_model
from unifi_profile_loader import ProfileError, load_profile
from unifi_raw_collector import RawCollector
from unifi_api import UniFiAPICollector, api_disabled

PROFILE_DIRECTORY = Path(__file__).with_name("unifi_profiles")
MODEL_CATALOG = load_catalog(MODEL_DIRECTORY)


def not_configured_unifi():
    return {
        "configured": False, "profile": None,
        "transport": {"status": "disabled", "last_attempt": None, "last_success": None},
        "api": api_disabled(),
        "system": None, "fans": [], "power_supplies": [],
        "storage": {
            "nvme": {"supported": "unknown", "present": "unknown", "observed": False, "capacity_bytes": None},
            "sata_ssd": {"supported": "unknown", "present": "unknown", "observed": False, "capacity_bytes": None},
            "tf": {"supported": "unknown", "present": "unknown", "observed": False, "capacity_bytes": None},
        },
        "diagnostics": {"collection_status": "not_collected", "ignored_observations": []},
        "updated_at": None, "stale": False, "error": None,
    }


def not_collected_unifi(profile_id):
    result = not_configured_unifi()
    result.update({
        "configured": True, "profile": profile_id,
        "transport": {"status": "not_collected", "last_attempt": None, "last_success": None},
        "stale": True,
        "error": {"code": "not_collected", "message": "UniFi telemetry has not been collected", "source": "unifi", "retryable": True, "http_status": None},
    })
    return result


def _runtime_model_from_api(api):
    """Resolve static capabilities only from the API's verified runtime model."""
    if not isinstance(api, dict):
        return None
    telemetry = api.get("telemetry")
    identity = telemetry.get("identity") if isinstance(telemetry, dict) else None
    runtime_model = identity.get("model") if isinstance(identity, dict) else None
    return project_static_capabilities(resolve_model(MODEL_CATALOG, runtime_model, kind="api_model"))


def _public(payload):
    result = copy.deepcopy(payload)
    result.pop("_cpu_baseline", None)
    result["configured"] = True
    return result


class UniFiDomainCollector:
    def __init__(self, config, *, raw_collector=None):
        self.config = config
        try:
            self.profile = load_profile(PROFILE_DIRECTORY, config.profile_id)
        except ProfileError as exc:
            raise ValueError("unknown_profile") from exc
        # The profile selects collection sources only. It cannot establish
        # the hardware identity or authorize static capability projection.
        self.model = None
        hwmon_expected_name = self.profile.get("diagnostics", {}).get("hwmon", {}).get("expected_name")
        self.raw_collector = raw_collector or RawCollector(config, hwmon_expected_name=hwmon_expected_name)
        api_config = getattr(config, "api", None)
        self.api_collector = UniFiAPICollector(api_config, target_profile=config.profile_id) if api_config is not None and getattr(api_config, "enabled", False) else None
        self.previous = None

    def collect(self):
        raw = self.raw_collector.collect()
        # Diagnostics are a fixed, read-only second pass.  They are kept
        # optional so a cache/sensor failure cannot invalidate core SSH data.
        if raw.get("transport", {}).get("ok") is True:
            try:
                raw["diagnostics"] = self.raw_collector.diagnostics()
            except Exception:
                raw["diagnostics"] = {"collection_status": "unavailable"}
        else:
            raw["diagnostics"] = {"collection_status": "unavailable"}
        if self.config.profile_id == "udw" and raw.get("transport", {}).get("ok") is True:
            raw["filesystem"] = self.raw_collector.filesystem()
        raw["api"] = self.api_collector.collect() if self.api_collector is not None else api_disabled()
        self.model = _runtime_model_from_api(raw["api"])
        try:
            normalized = normalize(self.profile, raw, self.previous, self.model)
        except ValueError:
            raw = {"collected_at": raw.get("collected_at"), "transport": {"ok": False, "error": "parse_failure"}}
            normalized = normalize(self.profile, raw, self.previous, self.model)
        public = _public(normalized)
        if not public["stale"]:
            self.previous = copy.deepcopy(public)
            self.previous["_cpu_baseline"] = normalized["_cpu_baseline"]
        return public
