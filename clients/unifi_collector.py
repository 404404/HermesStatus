"""UniFi domain adapter for the HermesStatus host extension lifecycle."""
from __future__ import annotations

import copy
from pathlib import Path
from unifi_normalizer import normalize
from unifi_profile_loader import ProfileError, load_profile
from unifi_raw_collector import RawCollector

PROFILE_DIRECTORY = Path(__file__).with_name("unifi_profiles")

def not_configured_unifi():
    return {"configured": False, "profile": None, "transport": {"status": "disabled", "last_attempt": None, "last_success": None}, "system": None, "fans": [], "power_supplies": [], "storage": {"nvme": {"supported": "unknown", "present": "unknown", "observed": "unknown"}}, "diagnostics": {}, "updated_at": None, "stale": False, "error": None}

def _public(payload):
    result = copy.deepcopy(payload)
    result.pop("_cpu_baseline", None)
    result.pop("previous_observation", None)
    result["configured"] = True
    transport = result.setdefault("transport", {})
    transport.setdefault("status", "available" if not result.get("stale") else "unavailable")
    transport.setdefault("last_success", result.get("updated_at"))
    return result

class UniFiDomainCollector:
    def __init__(self, config, *, raw_collector=None):
        self.config = config
        try:
            self.profile = load_profile(PROFILE_DIRECTORY, config.profile_id)
        except ProfileError as exc:
            raise ValueError("unknown_profile") from exc
        self.raw_collector = raw_collector or RawCollector(config)
        self.previous = None

    def collect(self):
        raw = self.raw_collector.collect()
        normalized = normalize(self.profile, raw, self.previous)
        if not normalized.get("stale"):
            self.previous = copy.deepcopy(normalized)
        return _public(normalized)
