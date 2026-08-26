import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from unifi_profile_loader import load_profile
from unifi_normalizer import normalize

class TransportSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(ROOT / "unifi_profiles", "ucg-max")

    def test_ssh_failure_is_null_stale_not_zero(self):
        result = normalize(self.profile, {"target_id": "ucg-max", "collected_at": "2026-08-23T00:00:00+00:00", "transport": {"ok": False}})
        self.assertTrue(result["stale"])
        self.assertEqual(result["error"]["code"], "ssh_transport_failure")
        self.assertIsNone(result["system"])

    def test_recovery_is_fresh(self):
        raw = {"target_id": "ucg-max", "collected_at": "2026-08-23T00:00:01+00:00", "transport": {"ok": True}, "generic": {"cpu_temperature_raw": "66.5", "proc_stat_cpu": "cpu 1 2 3 4 5 0 0 0 0 0", "meminfo": {"MemTotal": "10", "MemAvailable": "5", "MemFree": "4", "Buffers": "1", "Cached": "1", "SwapTotal": "0", "SwapFree": "0"}, "uptime_raw": "1.0 1.0", "loadavg_raw": "0.1 0.2 0.3 1/1 1"}, "diagnostics": {}}
        result = normalize(self.profile, raw)
        self.assertFalse(result["stale"])
        self.assertIsNone(result["error"])
        self.assertIsNone(result["system"]["cpu_usage_pct"])
