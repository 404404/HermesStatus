import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from unifi_collector import UniFiDomainCollector, not_collected_unifi, not_configured_unifi
from unifi_normalizer import _parse_cpu, normalize
from unifi_profile_loader import load_profile


def fixture(name):
    return json.loads((ROOT / "unifi_fixtures" / name).read_text(encoding="utf-8"))


class _Config:
    profile_id = "ucg-max"


class _Raw:
    def __init__(self, results):
        self.results = iter(results)
    def collect(self):
        return next(self.results)


class UniFiContractTests(unittest.TestCase):
    def setUp(self):
        self.ucg = load_profile(ROOT / "unifi_profiles", "ucg-max")
        self.udw = load_profile(ROOT / "unifi_profiles", "udw")

    def test_disabled_domain_is_explicit_and_empty(self):
        result = not_configured_unifi()
        self.assertFalse(result["configured"])
        self.assertEqual(result["transport"]["status"], "disabled")
        self.assertFalse(result["storage"]["nvme"]["observed"])
        self.assertEqual(set(result["storage"]), {"nvme", "sata_ssd", "tf"})
        self.assertEqual(result["fans"], [])
        pending = not_collected_unifi("udw")
        self.assertTrue(pending["configured"])
        self.assertEqual(pending["transport"]["status"], "not_collected")
        self.assertTrue(pending["stale"])

    def test_cpu_delta_invalid_cases_are_null_not_zero(self):
        first = normalize(self.ucg, fixture("ucg-max-raw.json"))
        cases = {
            "counter_reset": "cpu 1 1 1 1 0",
            "zero_delta": first["_cpu_baseline"],
        }
        reset_raw = fixture("ucg-max-raw.json")
        reset_raw["generic"]["proc_stat_cpu"] = cases["counter_reset"]
        reset = normalize(self.ucg, reset_raw, first)
        self.assertIsNone(reset["system"]["cpu_usage_percent"])
        self.assertEqual(reset["system"]["cpu_usage_reason"], "counter_reset")
        zero_raw = fixture("ucg-max-raw.json")
        baseline = first["_cpu_baseline"]
        zero_raw["generic"]["proc_stat_cpu"] = "cpu  %d 0 0 %d 0" % (baseline["total"] - baseline["idle"], baseline["idle"])
        zero = normalize(self.ucg, zero_raw, first)
        self.assertIsNone(zero["system"]["cpu_usage_percent"])
        self.assertEqual(zero["system"]["cpu_usage_reason"], "zero_delta")

    def test_cpu_delta_idle_busy_invalid_and_multicore_inputs(self):
        first = normalize(self.ucg, fixture("ucg-max-raw.json"))
        baseline = first["_cpu_baseline"]
        idle_raw = fixture("ucg-max-raw.json")
        idle_raw["generic"]["proc_stat_cpu"] = "cpu  %d 0 0 %d 0" % (baseline["total"] - baseline["idle"], baseline["idle"] + 100)
        idle = normalize(self.ucg, idle_raw, first)
        self.assertEqual(idle["system"]["cpu_usage_percent"], 0.0)
        busy_raw = fixture("ucg-max-raw.json")
        busy_raw["generic"]["proc_stat_cpu"] = "cpu  %d 0 0 %d 0" % (baseline["total"] - baseline["idle"] + 100, baseline["idle"])
        busy = normalize(self.ucg, busy_raw, first)
        self.assertEqual(busy["system"]["cpu_usage_percent"], 100.0)
        with self.assertRaises(ValueError):
            _parse_cpu("cpu 1 2")
        with self.assertRaises(ValueError):
            _parse_cpu("cpu0 1 2 3 4")
        with self.assertRaises(ValueError):
            _parse_cpu("cpu 1 2 3 4\ncpu0 1 2 3 4")

    def test_memory_fallback_is_explicit_and_never_negative(self):
        raw = fixture("ucg-max-raw.json")
        raw["generic"]["meminfo"].pop("MemAvailable")
        result = normalize(self.ucg, raw)
        memory = result["system"]["memory"]
        self.assertEqual(memory["available_source"], "fallback_memfree_buffers_cached")
        self.assertGreaterEqual(memory["used_bytes"], 0)
        self.assertEqual(memory["total_bytes"], memory["used_bytes"] + memory["available_bytes"])
        impossible = fixture("ucg-max-raw.json")
        impossible["generic"]["meminfo"]["MemAvailable"] = str(int(impossible["generic"]["meminfo"]["MemTotal"]) + 1)
        with self.assertRaises(ValueError):
            normalize(self.ucg, impossible)

    def test_capability_state_is_not_inferred_from_zero_or_tooling(self):
        ucg = normalize(self.ucg, fixture("ucg-max-raw.json"))
        self.assertEqual(ucg["fans"][0]["present"], "unknown")
        self.assertTrue(ucg["fans"][0]["observed"])
        self.assertEqual(ucg["fans"][0]["rpm"], 0)
        self.assertEqual(ucg["storage"]["nvme"], {"supported": "unknown", "present": "unknown", "observed": False, "capacity_bytes": None})
        self.assertEqual(ucg["storage"]["sata_ssd"], {"supported": "unknown", "present": "unknown", "observed": False, "capacity_bytes": None})
        self.assertEqual(ucg["storage"]["tf"], {"supported": "unknown", "present": "unknown", "observed": False, "capacity_bytes": None})
        udw = normalize(self.udw, fixture("udw-raw.json"))
        self.assertEqual([fan["id"] for fan in udw["fans"]], ["fan1", "fan2"])
        self.assertEqual([item["id"] for item in udw["diagnostics"]["ignored_observations"]], ["fan3", "fan4"])
        self.assertEqual([psu["present"] for psu in udw["power_supplies"]], ["unknown", "unknown"])

    def test_failure_preserves_previous_values_and_marks_only_unifi_stale(self):
        raw = fixture("ucg-max-raw.json")
        raw["collected_at"] = "2026-08-23T00:00:00+00:00"
        failed = {"collected_at": "2026-08-23T00:01:00+00:00", "transport": {"ok": False, "error": "host_key_failure"}}
        collector = UniFiDomainCollector(_Config(), raw_collector=_Raw([raw, failed]))
        first, second = collector.collect(), collector.collect()
        self.assertFalse(first["stale"])
        self.assertTrue(second["stale"])
        self.assertEqual(second["error"]["code"], "host_key_failure")
        self.assertEqual(second["system"], first["system"])
        self.assertEqual(second["transport"]["last_success"], first["updated_at"])
        timeout = normalize(self.ucg, {"collected_at": "2026-08-23T00:02:00+00:00", "transport": {"ok": False, "error": "ssh_timeout"}}, first)
        self.assertEqual(timeout["error"]["code"], "ssh_timeout")

    def test_parse_failure_does_not_make_zero_metrics(self):
        raw = fixture("ucg-max-raw.json")
        raw["generic"]["proc_stat_cpu"] = "cpu invalid"
        collector = UniFiDomainCollector(_Config(), raw_collector=_Raw([raw]))
        result = collector.collect()
        self.assertTrue(result["stale"])
        self.assertIsNone(result["system"])
        self.assertEqual(result["error"]["code"], "parse_failure")


if __name__ == "__main__":
    unittest.main()
