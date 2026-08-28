import os
import stat
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from unifi_api import API_ENDPOINTS, APIError, UniFiAPICollector, _read_key


class UniFiAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key = Path(self.tmp.name) / "api-key"
        self.key.write_text("redacted-test-key\n", encoding="ascii")
        os.chmod(self.key, 0o600)
        self.config = SimpleNamespace(
            base_url="https://192.168.68.1:443", api_key_file=str(self.key),
            ca_file=None, tls_sha256=None, timeout_seconds=3
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_key_is_file_backed_and_not_returned_by_payload(self):
        self.assertEqual(_read_key(str(self.key)), "redacted-test-key")
        result = UniFiAPICollector(self.config, request=lambda config, path, key: ({}, 200)).collect()
        self.assertNotIn("redacted-test-key", repr(result))
        self.assertEqual(len(result["endpoints"]), len(API_ENDPOINTS))

    def test_symlink_and_insecure_key_are_rejected(self):
        link = Path(self.tmp.name) / "link"
        link.symlink_to(self.key)
        with self.assertRaises(APIError) as ctx:
            _read_key(str(link))
        self.assertEqual(ctx.exception.code, "api_key_file_error")
        os.chmod(self.key, 0o644)
        with self.assertRaises(APIError):
            _read_key(str(self.key))

    def test_auth_failure_is_classified_and_stops_fixed_registry(self):
        calls = []
        def request(config, path, key):
            calls.append(path)
            raise APIError("api_auth_failure", status=401)
        result = UniFiAPICollector(self.config, request=request).collect()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["error"]["code"], "api_auth_failure")
        self.assertEqual(result["error"]["http_status"], 401)
        self.assertEqual(calls, [path for _, path in API_ENDPOINTS])
        self.assertEqual(len(result["endpoints"]), len(API_ENDPOINTS))

    def test_success_is_direct_json_and_fixed_get_paths(self):
        calls = []
        def request(config, path, key):
            calls.append((path, key))
            return ({"model": "UCG Max", "version": "5.1"} if path.endswith("/info") else []), 200
        result = UniFiAPICollector(self.config, request=request).collect()
        self.assertEqual(result["status"], "available")
        self.assertEqual([path for path, _ in calls], [path for _, path in API_ENDPOINTS])
        self.assertEqual(result["summary"]["model"], "UCG Max")
        self.assertEqual(result["summary"]["firmware"], "5.1")
        self.assertTrue(all(key == "redacted-test-key" for _, key in calls))


    def test_partial_endpoint_failure_preserves_successful_telemetry(self):
        def request(config, path, key):
            if path.endswith("/devices"):
                raise APIError("api_endpoint_unsupported", status=404)
            if path.endswith("/info"):
                return ({"model": "UDW", "firmwareVersion": "5.0.1", "applicationVersion": "9.1.2"}, 200)
            if path.endswith("/clients"):
                return ({"data": [{"connectionType": "wired"}, {"connectionType": "wireless"}]}, 200)
            if path.endswith("/networks"):
                return ({"data": [{"purpose": "vlan"}, {"purpose": "corporate"}]}, 200)
            return ({"data": []}, 200)
        result = UniFiAPICollector(self.config, request=request).collect()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["error"]["code"], "api_partial_failure")
        self.assertEqual(result["telemetry"]["clients"], {"total": 2, "wired": 1, "wireless": 1, "observed": True})
        self.assertEqual(result["telemetry"]["networks"], {"total": 2, "vlan": 1})
        failed = next(item for item in result["endpoints"] if item["name"] == "devices")
        self.assertEqual(failed["status"], "unsupported")
        self.assertEqual(failed["error"]["code"], "api_endpoint_unsupported")

    def test_api_telemetry_shape_is_bounded_and_zero_is_preserved(self):
        def request(config, path, key):
            if path.endswith("/info"):
                return ({"modelName": "UDW", "firmware_version": "5.0.1", "application_version": "9.1.2"}, 200)
            if path.endswith("/devices"):
                return ({"data": [{"name": "WAN1", "status": "online", "isp": "Example ISP", "latencyMs": 0, "packetLossPercent": 0, "rxBps": 0, "txBps": 123, "uplinks": [{"name": "eth0", "linkState": "up", "speedMbps": 1000}], "temperatures": [{"id": "cpu", "label": "CPU", "celsius": 64.5}]}]}, 200)
            if path.endswith("/clients"):
                return ({"data": []}, 200)
            if path.endswith("/networks"):
                return ({"data": []}, 200)
            return ({"data": []}, 200)
        result = UniFiAPICollector(self.config, request=request).collect()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["telemetry"]["identity"]["model"], "UDW")
        self.assertEqual(result["telemetry"]["wans"][0]["latency_ms"], 0)
        self.assertEqual(result["telemetry"]["wans"][0]["rx_bps"], 0)
        self.assertEqual(result["telemetry"]["uplinks"][0]["speed_mbps"], 1000)
        self.assertEqual(result["telemetry"]["temperatures"][0]["celsius"], 64.5)

    def test_all_endpoint_failure_is_unavailable_with_no_raw_payload(self):
        result = UniFiAPICollector(self.config, request=lambda config, path, key: (_ for _ in ()).throw(APIError("api_auth_failure", status=401))).collect()
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["telemetry"])
        self.assertNotIn("401", repr(result["error"]) if result["error"]["http_status"] is None else "")

    def test_failure_classes_are_distinct(self):
        for code in ("api_timeout", "api_tls_failure", "api_parse_failure", "api_endpoint_unsupported"):
            result = UniFiAPICollector(self.config, request=lambda config, path, key, code=code: (_ for _ in ()).throw(APIError(code))).collect()
            self.assertEqual(result["error"]["code"], code)


if __name__ == "__main__":
    unittest.main()
