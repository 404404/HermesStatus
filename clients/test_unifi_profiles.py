import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from unifi_profile_loader import ProfileError, load_profile, validate_profile

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.profiles = ROOT / "unifi_profiles"

    def test_schema_version_and_loads(self):
        self.assertEqual(load_profile(self.profiles, "udw")["schema_version"], 1)
        self.assertEqual(load_profile(self.profiles, "ucg-max")["profile_id"], "ucg-max")

    def test_unknown_profile_rejected(self):
        with self.assertRaisesRegex(ProfileError, "unknown_profile"):
            load_profile(self.profiles, "not-a-profile")

    def test_storage_capabilities_capture_udw_media(self):
        udw = load_profile(self.profiles, "udw")
        self.assertEqual(set(udw["storage"]), {"nvme", "sata_ssd", "tf"})
        self.assertEqual(udw["storage"]["nvme"]["supported"], False)
        self.assertEqual(udw["storage"]["sata_ssd"]["capacity_bytes"], 128000000000)
        self.assertEqual(udw["storage"]["tf"]["present"], "not_populated")
        self.assertEqual(udw["cpu_model"], "Annapurna AL324")

    def test_ucg_max_profile_declares_cpu_and_nvme_capability(self):
        ucg = load_profile(self.profiles, "ucg-max")
        self.assertEqual(ucg["cpu_model"], "Qualcomm IPQ5322")
        self.assertEqual(ucg["diagnostics"]["hwmon"]["source"], "linux.sensors_json")
        self.assertEqual(ucg["diagnostics"]["hwmon"]["expected_name"], "lm63")
        self.assertTrue(ucg["storage"]["nvme"]["supported"])
        self.assertFalse(ucg["storage"]["sata_ssd"]["supported"])

    def test_fixed_poe_and_power_limits_are_profile_data(self):
        udw = load_profile(self.profiles, "udw")
        self.assertTrue(udw["poe"]["supported"])
        self.assertEqual(udw["poe"]["total_max_power_w"], 420)
        self.assertEqual(udw["poe"]["port_max_power_w"]["1"], 15.4)
        self.assertEqual(udw["poe"]["port_max_power_w"]["12"], 60)
        self.assertEqual(udw["power"]["max_power_w"], 550)
        ucg = load_profile(self.profiles, "ucg-max")
        self.assertFalse(ucg["poe"]["supported"])
        self.assertIsNone(ucg["power"]["max_power_w"])

    def test_unknown_source_rejected(self):
        profile = copy.deepcopy(load_profile(self.profiles, "udw"))
        profile["generic"]["memory"]["source"] = "arbitrary_shell"
        with self.assertRaisesRegex(ProfileError, "unknown source"):
            validate_profile(profile)

    def test_unknown_presence_rejected(self):
        profile = copy.deepcopy(load_profile(self.profiles, "udw"))
        profile["fans"]["channels"][0]["present"] = "maybe"
        with self.assertRaisesRegex(ProfileError, "invalid fan capability"):
            validate_profile(profile)

    def test_duplicate_fans_rejected(self):
        profile = copy.deepcopy(load_profile(self.profiles, "udw"))
        profile["fans"]["channels"][1]["id"] = "fan1"
        with self.assertRaisesRegex(ProfileError, "duplicate"):
            validate_profile(profile)

    def test_no_arbitrary_command_field(self):
        profile = copy.deepcopy(load_profile(self.profiles, "udw"))
        profile["generic"]["uptime"]["command"] = "id"
        with self.assertRaisesRegex(ProfileError, "invalid source definition"):
            validate_profile(profile)

    def test_fixtures_have_no_secret_fields(self):
        forbidden = ("password", "authorization", "opentoken", "private_key", "credential")
        for path in (ROOT / "unifi_fixtures").glob("*.json"):
            self.assertFalse(any(word in path.read_text(encoding="utf-8").lower() for word in forbidden), path.name)
