import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from unifi_profile_loader import load_profile
from unifi_model_catalog import MODEL_DIRECTORY, load_catalog
from unifi_normalizer import normalize

def fixture(name):
    return json.loads((ROOT / "unifi_fixtures" / name).read_text(encoding="utf-8"))

class NormalizerTests(unittest.TestCase):
    def setUp(self):
        self.profiles = ROOT / "unifi_profiles"
        self.models = load_catalog(MODEL_DIRECTORY)

    def test_udw_normalization_and_fans(self):
        result = normalize(load_profile(self.profiles, "udw"), fixture("udw-raw.json"), model=self.models["UDW"])
        self.assertEqual(result["system"]["cpu_temperature_c"], 64.0)
        self.assertEqual(result["system"]["cpu_model"], "Annapurna AL324")
        self.assertEqual([x["id"] for x in result["fans"]], ["fan1", "fan2", "fan3", "fan4"])
        self.assertTrue(all(x["supported"] == "unknown" and x["present"] == "present" and x["observed"] for x in result["fans"]))
        self.assertEqual(result["diagnostics"]["ignored_observations"], [])
        self.assertEqual(result["storage"]["nvme"]["supported"], "unsupported")
        self.assertEqual(result["storage"]["nvme"]["present"], "not_present")
        self.assertEqual(result["storage"]["sata_ssd"]["supported"], "supported")
        self.assertEqual(result["storage"]["sata_ssd"]["capacity_bytes"], 128000000000)
        self.assertEqual(result["storage"]["tf"]["present"], "present")
        self.assertEqual(result["power"]["psu_slots"], 2)
        self.assertEqual(result["power"]["max_device_consumption_w"], 532)
        self.assertTrue(result["poe"]["supported"])
        self.assertEqual(result["system"]["cpu_usage_percent"], None)

    def test_ucg_max_zero_rpm_is_not_failure_and_nvme_unknown(self):
        result = normalize(load_profile(self.profiles, "ucg-max"), fixture("ucg-max-raw.json"), model=self.models["UCG-Max"])
        self.assertEqual(result["fans"][0]["rpm"], 0)
        self.assertEqual(result["fans"][0]["state"], "observed_zero_rpm")
        self.assertEqual(result["fans"][0]["supported"], "unknown")
        self.assertEqual(result["fans"][0]["present"], "present")
        self.assertEqual(result["storage"]["nvme"]["present"], "not_present")
        self.assertFalse(result["storage"]["nvme"]["observed"])
        self.assertEqual(result["storage"]["nvme"]["supported"], "supported")
        self.assertEqual(result["storage"]["sata_ssd"]["supported"], "unsupported")
        self.assertEqual(result["storage"]["tf"]["present"], "not_present")
        self.assertEqual(result["system"]["cpu_model"], "Qualcomm IPQ5322")
        self.assertFalse(result["power"]["supported"])

    def test_memory_uptime_load_and_cpu_delta(self):
        profile = load_profile(self.profiles, "ucg-max")
        first = normalize(profile, fixture("ucg-max-raw.json"), model=self.models["UCG-Max"])
        second_raw = fixture("ucg-max-raw.json")
        second_raw["generic"]["proc_stat_cpu"] = "cpu  2100 210 850 16200 405 0 0 0 0 0"
        second = normalize(profile, second_raw, first, model=self.models["UCG-Max"])
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
            "flash_sysfs": {"1": {"node": "sda", "info": {"size": 64000000000}}},
            "sdcard": {"1": {"node": None, "present": False}},
            "psu": {"0": {"label": "psu1", "present": True, "power": 48.0, "fan": {"0": 3672}}, "1": {"label": "psu2", "present": False, "power": 0, "fan": {"0": 0}}}
        }}
        result = normalize(load_profile(self.profiles, "udw"), raw, model=self.models["UDW"])
        self.assertEqual([fan["rpm"] for fan in result["fans"]], [1611, 2657])
        self.assertEqual(result["power_supplies"][0]["present"], "present")
        self.assertEqual(result["power_supplies"][0]["power_w"], 48.0)
        self.assertEqual(result["power_supplies"][0]["fan_rpm"], 3672)
        self.assertTrue(result["power_supplies"][0]["observed"])
        self.assertEqual(result["storage"]["sata_ssd"]["capacity_bytes"], 128000000000)
        self.assertTrue(result["storage"]["sata_ssd"]["observed"])
        self.assertEqual(result["storage"]["tf"]["present"], "not_present")

    def test_udw_filesystem_usage_is_separate_from_static_capacity(self):
        raw = fixture("udw-raw.json")
        raw["filesystem"] = {
            "status": "available", "mountpoint": "/ssd1", "device": "/dev/sda5",
            "filesystem_total_bytes": 109000000000, "used_bytes": 106000000000,
            "available_bytes": 3000000000, "usage_percent": 97.25,
        }
        result = normalize(load_profile(self.profiles, "udw"), raw, model=self.models["UDW"])
        sata = result["storage"]["sata_ssd"]
        self.assertEqual(sata["capacity_bytes"], 128000000000)
        self.assertEqual(sata["filesystem_total_bytes"], 109000000000)
        self.assertEqual(sata["used_bytes"], 106000000000)
        self.assertEqual(sata["available_bytes"], 3000000000)
        self.assertEqual(sata["usage_percent"], 97.25)
        self.assertTrue(sata["observed"])

    def test_udw_missing_filesystem_observation_is_optional(self):
        raw = fixture("udw-raw.json")
        raw["filesystem"] = {"status": "unavailable", "mountpoint": "/ssd1"}
        result = normalize(load_profile(self.profiles, "udw"), raw, model=self.models["UDW"])
        self.assertNotIn("filesystem_total_bytes", result["storage"]["sata_ssd"])
        self.assertEqual(result["storage"]["sata_ssd"]["capacity_bytes"], 128000000000)

    def test_ucg_max_missing_fan_rpm_is_not_observed(self):
        raw = fixture("ucg-max-raw.json")
        raw["diagnostics"]["fans"] = {}
        result = normalize(load_profile(self.profiles, "ucg-max"), raw, model=self.models["UCG-Max"])
        self.assertEqual(result["fans"], [])

    def test_unknown_fan_without_rpm_does_not_infer_absence(self):
        raw = fixture("ucg-max-raw.json")
        raw["diagnostics"]["fans"] = {"fan1": None}
        result = normalize(load_profile(self.profiles, "ucg-max"), raw, model=self.models["UCG-Max"])
        self.assertEqual(result["fans"], [{"id": "fan1", "supported": "unknown", "present": "unknown", "observed": False, "rpm": None, "state": "not_observed", "error": None}])

    def test_zero_psu_sensor_is_positive_presence_evidence(self):
        raw = fixture("udw-raw.json")
        raw["diagnostics"] = {"collection_status": "available", "hardware_cache_status": "available", "hardware_cache": {
            "psu": {"0": {"label": "psu1", "present": False, "power": 0, "fan": {"0": 0}}}
        }}
        result = normalize(load_profile(self.profiles, "udw"), raw, model=self.models["UDW"])
        self.assertEqual(result["power_supplies"][0]["present"], "present")
        self.assertTrue(result["power_supplies"][0]["observed"])


    def test_public_shape_exposes_catalog_power_and_poe_metadata(self):
        result = normalize(load_profile(self.profiles, "udw"), fixture("udw-raw.json"), model=self.models["UDW"])
        self.assertEqual(result["power"]["supported"], True)
        self.assertEqual(result["power"]["psu_slots"], 2)
        self.assertEqual(result["power"]["psu_unit_capacity_w"], 550)
        self.assertEqual(result["poe"]["total_max_power_w"], 420)
        self.assertNotIn("max_power_w", result["power_supplies"][0])

    def test_fan_observation_is_ignored_when_target_identity_does_not_match_profile(self):
        raw = fixture("ucg-max-raw.json")
        raw["target_id"] = "udw"
        result = normalize(load_profile(self.profiles, "ucg-max"), raw, model=self.models["UCG-Max"])
        self.assertEqual(result["fans"], [])

    def test_optional_diagnostics_do_not_break_core(self):
        raw = fixture("ucg-max-raw.json")
        raw["diagnostics"] = {"collection_status": "unavailable"}
        result = normalize(load_profile(self.profiles, "ucg-max"), raw, model=self.models["UCG-Max"])
        self.assertEqual(result["system"]["cpu_temperature_c"], 67.1)
        self.assertFalse(result["stale"])

    def test_storage_and_power_capabilities_come_from_model_catalog(self):
        profile = load_profile(self.profiles, "udw")
        result = normalize(profile, fixture("udw-raw.json"), model=self.models["UDW"])
        self.assertTrue(result["power"]["supported"])
        self.assertEqual(result["power"]["psu_slots"], 2)
        self.assertEqual(result["power"]["psu_unit_capacity_w"], 550)
        self.assertEqual(result["power"]["controller_reference_capacity_w"], 550)
        self.assertEqual(result["power"]["max_device_consumption_w"], 532)
        self.assertEqual(result["power"]["absolute_max_poe_budget_w"], 420)
        self.assertEqual(result["storage"]["sata_ssd"]["supported"], "supported")
        self.assertEqual(result["storage"]["sata_ssd"]["present"], "present")

    def test_unknown_runtime_model_preserves_observations_without_static_capabilities(self):
        raw = fixture("ucg-max-raw.json")
        raw["diagnostics"]["hardware_cache"] = {
            "storage": {"1": {"category": "nvme", "capacity_bytes": 123456789}}
        }
        result = normalize(load_profile(self.profiles, "ucg-max"), raw)
        self.assertIsNone(result["power"])
        self.assertIsNone(result["poe"])
        self.assertIsNone(result["system"]["cpu_model"])
        self.assertEqual(result["fans"][0]["rpm"], 0)
        self.assertEqual(result["fans"][0]["supported"], "unknown")
        self.assertEqual(result["fans"][0]["present"], "present")
        self.assertEqual(result["storage"]["nvme"]["supported"], "unknown")
        self.assertEqual(result["storage"]["nvme"]["capacity_bytes"], 123456789)
        self.assertEqual(result["storage"]["nvme"]["present"], "present")
        self.assertTrue(result["storage"]["nvme"]["observed"])
        self.assertTrue(all(item["supported"] == "unknown" for name, item in result["storage"].items() if name != "nvme"))

    def test_complete_catalog_storage_enumeration_marks_absent_media_unsupported(self):
        result = normalize(load_profile(self.profiles, "ucg-max"), fixture("ucg-max-raw.json"), model=self.models["UCG-Max"])
        self.assertEqual(result["storage"]["nvme"]["supported"], "supported")
        self.assertEqual(result["storage"]["nvme"]["present"], "not_present")
        self.assertEqual(result["storage"]["sata_ssd"]["supported"], "unsupported")
        self.assertEqual(result["storage"]["sata_ssd"]["present"], "not_present")
        self.assertEqual(result["storage"]["tf"]["supported"], "unsupported")
        self.assertEqual(result["storage"]["tf"]["present"], "not_present")
