import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from unifi_profile_loader import load_profile
from unifi_normalizer import normalize

def fixture(name):
    return json.loads((ROOT / "unifi_fixtures" / name).read_text(encoding="utf-8"))

class NormalizerTests(unittest.TestCase):
    def setUp(self):
        self.profiles = ROOT / "unifi_profiles"

    def test_udw_normalization_and_fans(self):
        result = normalize(load_profile(self.profiles, "udw"), fixture("udw-raw.json"))
        self.assertEqual(result["system"]["cpu_temperature_c"], 64.0)
        self.assertEqual(result["system"]["cpu_model"], "Annapurna AL324")
        self.assertEqual([x["id"] for x in result["fans"]], ["fan1", "fan2"])
        self.assertEqual([x["id"] for x in result["diagnostics"]["ignored_observations"]], ["fan3", "fan4"])
        self.assertEqual(result["storage"]["nvme"]["supported"], "unsupported")
        self.assertEqual(result["storage"]["nvme"]["present"], "not_present")
        self.assertEqual(result["storage"]["sata_ssd"]["supported"], "supported")
        self.assertEqual(result["storage"]["sata_ssd"]["capacity_bytes"], 128000000000)
        self.assertEqual(result["storage"]["tf"]["present"], "not_present")
        self.assertEqual(result["system"]["cpu_usage_percent"], None)

    def test_ucg_max_zero_rpm_is_not_failure_and_nvme_unknown(self):
        result = normalize(load_profile(self.profiles, "ucg-max"), fixture("ucg-max-raw.json"))
        self.assertEqual(result["fans"][0]["rpm"], 0)
        self.assertEqual(result["fans"][0]["state"], "observed_zero_rpm")
        self.assertEqual(result["storage"]["nvme"]["present"], "unknown")
        self.assertFalse(result["storage"]["nvme"]["observed"])
        self.assertEqual(result["storage"]["nvme"]["supported"], "unknown")
        self.assertEqual(result["storage"]["sata_ssd"]["supported"], "unknown")
        self.assertEqual(result["storage"]["tf"]["present"], "unknown")

    def test_memory_uptime_load_and_cpu_delta(self):
        profile = load_profile(self.profiles, "ucg-max")
        first = normalize(profile, fixture("ucg-max-raw.json"))
        second_raw = fixture("ucg-max-raw.json")
        second_raw["generic"]["proc_stat_cpu"] = "cpu  2100 210 850 16200 405 0 0 0 0 0"
        second = normalize(profile, second_raw, first)
        self.assertGreater(second["system"]["cpu_usage_percent"], 0)
        self.assertEqual(second["system"]["cpu_usage_reason"], None)
        self.assertEqual(second["system"]["memory"]["used_bytes"], 4194304000)
        self.assertEqual(second["system"]["uptime_seconds"], 23456.78)
        self.assertEqual(second["system"]["load_average"]["fifteen_minutes"], 0.39)

    def test_udw_hw_polling_cache_maps_fan_psu_and_storage(self):
        raw = fixture("udw-raw.json")
        raw["diagnostics"] = {"collection_status": "available", "hardware_cache_status": "available", "hardware_cache": {
            "thermal": {"1": {"fan_speed": 1611}, "2": {"fan_speed": 2657}, "3": {"fan_speed": -1}},
            "flash": {"1": {"node": "sda", "present": True}},
            "flash_sysfs": {"1": {"node": "sda", "info": {"size": 128000000000}}},
            "sdcard": {"1": {"node": None, "present": False}},
            "psu": {"0": {"label": "psu1", "present": True, "power": 48.0, "fan": {"0": 3672}}, "1": {"label": "psu2", "present": False, "power": 0, "fan": {"0": 0}}}
        }}
        result = normalize(load_profile(self.profiles, "udw"), raw)
        self.assertEqual([fan["rpm"] for fan in result["fans"]], [1611, 2657])
        self.assertEqual(result["power_supplies"][0]["present"], "present")
        self.assertEqual(result["power_supplies"][0]["power_w"], 48.0)
        self.assertEqual(result["power_supplies"][0]["fan_rpm"], 3672)
        self.assertTrue(result["power_supplies"][0]["observed"])
        self.assertEqual(result["storage"]["sata_ssd"]["capacity_bytes"], 128000000000)
        self.assertTrue(result["storage"]["sata_ssd"]["observed"])
        self.assertEqual(result["storage"]["tf"]["present"], "not_present")


    def test_optional_diagnostics_do_not_break_core(self):
        raw = fixture("ucg-max-raw.json")
        raw["diagnostics"] = {"collection_status": "unavailable"}
        result = normalize(load_profile(self.profiles, "ucg-max"), raw)
        self.assertEqual(result["system"]["cpu_temperature_c"], 67.1)
        self.assertFalse(result["stale"])
