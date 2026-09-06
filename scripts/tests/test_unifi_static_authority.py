import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_unifi_static_authority as guard


class UniFiStaticAuthorityGuardTests(unittest.TestCase):
    def test_current_tree_has_no_local_static_model_truth(self):
        self.assertEqual(guard.findings(), [])
        self.assertEqual(guard.collector_configuration_occurrences(), 16)

    def test_profile_static_keys_are_explicitly_forbidden(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "udw.json"
            path.write_text(json.dumps({"storage": {}}), encoding="utf-8")
            profile = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(sorted(guard.PROFILE_STATIC_KEYS & set(profile)), ["storage"])

    def test_legacy_profile_access_pattern_is_detected(self):
        pattern = next(pattern for label, pattern in guard.LEGACY_PATTERNS if label == "profile storage authority")
        self.assertIsNotNone(pattern.search('profile["storage"]'))
        self.assertIsNone(pattern.search('model["storage"]'))

    def test_catalog_bundle_is_not_scanned_as_local_authority(self):
        self.assertNotIn("unifi_catalog", {path.parent.name for path in guard.production_files()})


if __name__ == "__main__":
    unittest.main()
