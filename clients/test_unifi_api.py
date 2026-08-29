import os
import ssl
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from unifi_api import API_ENDPOINTS, APIError, UniFiAPICollector, _context, _read_key, _port_record, _ports, _merge_wans, _network_groups, _statistics_wans, _site_records, _v2_site_path, _legacy_site_path


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

    def test_explicit_pin_uses_pin_only_context_without_implicit_fallback(self):
        context = _context(None, "a" * 64)
        self.assertFalse(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)
        verified = _context(None, None)
        self.assertTrue(verified.check_hostname)
        self.assertEqual(verified.verify_mode, ssl.CERT_REQUIRED)

    def test_key_is_file_backed_and_not_returned_by_payload(self):
        self.assertEqual(_read_key(str(self.key)), "redacted-test-key")
        result = UniFiAPICollector(self.config, request=lambda config, path, key: ({}, 200), target_profile="udw").collect()
        self.assertNotIn("redacted-test-key", repr(result))

    def test_symlink_and_insecure_key_are_rejected(self):
        link = Path(self.tmp.name) / "link"
        link.symlink_to(self.key)
        with self.assertRaises(APIError) as ctx:
            _read_key(str(link))
        self.assertEqual(ctx.exception.code, "api_key_file_error")
        os.chmod(self.key, 0o644)
        with self.assertRaises(APIError):
            _read_key(str(self.key))

    def _fixture_request(self, calls, *, sites=None, devices=None, fail=None):
        sites = sites or [{"id": "site-a", "internalReference": "default", "name": "Default"}]
        devices = devices or [
            {"id": "ap-1", "model": "U6-Pro", "name": "Access Point", "state": "ONLINE"},
            {"id": "switch-1", "model": "USW", "name": "Switch", "state": "ONLINE"},
            {"id": "udw-1", "model": "UDW", "name": "UDW", "firmwareVersion": "5.0", "state": "ONLINE"},
        ]

        def request(config, path, key):
            calls.append(path)
            if fail and path.endswith(fail):
                raise APIError("api_endpoint_unsupported", status=404)
            if path.endswith("/info"):
                return {"applicationVersion": "10.5.67"}, 200
            if path.endswith("/sites"):
                return {"offset": 0, "limit": 25, "count": len(sites), "data": sites}, 200
            if "/devices/" in path and path.endswith("/statistics/latest"):
                return {"cpuUtilizationPct": 12.5, "memoryUtilizationPct": 41.0,
                        "loadAverage1Min": 1.1, "loadAverage5Min": 1.2,
                        "loadAverage15Min": 1.3, "uptimeSec": 1234,
                        "lastHeartbeatAt": "2026-01-01T00:00:00Z",
                        "uplink": {"rxRateBps": 100, "txRateBps": 200},
                        "wans": [{"id": "wan1", "status": {"state": "ONLINE", "isp": "Example ISP", "speedMbps": 2500},
                                  "metrics": {"latencyMs": 2.5, "packetLossPercent": 0.0, "jitterMs": 0.1}}]}, 200
            if "/devices/" in path:
                return {"id": "udw-1", "model": "UDW", "name": "UDW", "firmwareVersion": "5.0", "state": "ONLINE",
                        "interfaces": {"ports": [{"idx": 1, "state": "UP", "speedMbps": 2500, "maxSpeedMbps": 2500}, {"idx": 2, "state": "DOWN", "maxSpeedMbps": 1000}]}}, 200
            if path.endswith("/devices"):
                return {"data": devices}, 200
            if path.endswith("/clients"):
                return {"data": [{"id": "c1", "type": "WIRED"}, {"id": "c2", "type": "WIRELESS"}]}, 200
            if path.endswith("/networks"):
                return {"data": [{"id": "n1", "vlanId": 10}, {"id": "n2", "management": True}]}, 200
            if path.startswith("/proxy/network/api/s/") and path.endswith("/stat/device"):
                return {"data": [{"device_id": "udw-1", "model": "UDW", "port_table": [{"port_idx": 1, "name": "Port 1", "media": "GE", "up": True, "enable": True, "speed": 1000, "full_duplex": True, "autoneg": True, "is_uplink": True, "rx_bytes": 1000, "tx_bytes": 2000, "rx_packets": 10, "tx_packets": 20, "rx_errors": 0, "tx_errors": 1, "rx_dropped": 2, "tx_dropped": 3, "port_poe": False, "poe_power": "0.00", "last_connection": {"connected": True}}]}]}, 200
            if path.startswith("/proxy/network/api/s/") and path.endswith("/stat/health"):
                return {"data": [{"device_id": "udw-1", "wan_status": [{"id": "wan1", "isp_name": "Example ISP", "asn": 64500, "alive": True}]}]}, 200
            if path.startswith("/proxy/network/api/s/") and path.endswith("/stat/sysinfo"):
                return {"data": []}, 200
            if path.endswith("/switching/lags"):
                return {"data": []}, 200
            if path.endswith("/topology") or path.endswith("/ports/port-anomalies"):
                raise APIError("api_endpoint_unsupported", status=404)
            if path.endswith("/wans"):
                return {"data": [{"id": "wan1", "name": "Primary", "interface": "WAN"}, {"id": "wan2", "name": "WAN2", "interface": "WAN2"}]}, 200
            if path.endswith("/enriched-configuration"):
                return {"data": [{"id": "wan1", "networkGroup": "wan"}, {"id": "wan2", "networkGroup": "wan2"}]}, 200
            if path.endswith("/load-balancing/status"):
                return {"data": [{"id": "wan1", "role": "active"}, {"id": "wan2", "role": "backup"}]}, 200
            if path.endswith("/load-balancing/configuration"):
                return {"data": [{"id": "wan1", "priority": 1}, {"id": "wan2", "priority": 2}]}, 200
            if path.endswith("/wan-slas"):
                return {"data": []}, 200
            if path.endswith("/isp-status"):
                return {"data": [{"id": "wan1", "networkGroup": "wan", "speedtestHistory": [{"timestamp": "2026-01-01T00:00:00Z", "latencyMs": 2.5, "downloadMbps": 900, "uploadMbps": 100}]}]}, 200
            raise AssertionError(f"unexpected request path: {path}")

        return request

    def test_single_site_selection_and_site_scoped_paths(self):
        calls = []
        result = UniFiAPICollector(self.config, request=self._fixture_request(calls), target_profile="udw").collect()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["error"]["code"], "api_partial_failure")
        self.assertEqual([x["name"] for x in result["endpoints"]], [
            "info", "sites", "devices", "clients", "networks",
            "lags", "legacy_stat_device", "legacy_stat_health", "legacy_stat_sysinfo", "topology", "port_anomalies", "wan_official", "wan_enriched", "wan_load_balance", "wan_load_balance_config", "wan_slas", "wan_isp_status"
        ])
        self.assertIn("/proxy/network/integration/v1/sites/site-a/devices", calls)
        self.assertIn("/proxy/network/integration/v1/sites/site-a/clients", calls)
        self.assertIn("/proxy/network/integration/v1/sites/site-a/networks", calls)
        self.assertIn("/proxy/network/v2/api/site/default/topology", calls)
        self.assertIn("/proxy/network/api/s/default/stat/health", calls)
        self.assertNotIn("/proxy/network/integration/v1/devices", calls)
        self.assertNotIn("/proxy/network/integration/v1/clients", calls)
        self.assertNotIn("/proxy/network/integration/v1/networks", calls)
        telemetry = result["telemetry"]
        self.assertEqual(telemetry["wans"][0]["id"], "wan1")
        self.assertEqual(telemetry["wans"][0]["isp"], "Example ISP")
        self.assertEqual(telemetry["wans"][0]["role"], "active")
        self.assertEqual(telemetry["wans"][0]["asn"], "64500")
        self.assertEqual(telemetry["wans"][0]["speedtest"]["download_mbps"], 900.0)
        self.assertNotIn("packet_loss_percent", telemetry["wans"][0])
        self.assertEqual(telemetry["identity"]["model"], "UDW")
        self.assertEqual(telemetry["devices"]["total"], 3)
        self.assertEqual(telemetry["clients"], {"total": 2, "wired": 1, "wireless": 1, "observed": True})
        self.assertEqual(telemetry["networks"], {"total": 2, "vlan": 1})
        self.assertEqual(len(telemetry["ports"]), 1)
        self.assertEqual(telemetry["ports"][0]["port_idx"], 1)
        self.assertEqual(telemetry["ports"][0]["max_speed_mbps"], 2500)
        self.assertEqual(telemetry["ports"][0]["rx_bytes"], 1000)
        self.assertNotIn("rx_bps", telemetry["ports"][0])
        self.assertEqual(telemetry["port_summary"]["up"], 1)
        self.assertEqual(telemetry["port_summary"]["down"], 0)
        self.assertEqual(telemetry["lags"], [])
        self.assertIsNone(telemetry["topology"])
        self.assertIsNone(telemetry["anomalies"])
        # Latest-statistics rates are intentionally not projected into the
        # strict Device v2 uplink model (which only accepts link metadata).
        self.assertTrue(telemetry["uplinks"])
        self.assertTrue(all(set(item) <= {"name", "link_state", "speed_mbps", "duplex", "wan_id"}
                            for item in telemetry["uplinks"]))
        target_uplink = next(item for item in telemetry["uplinks"] if item.get("name") == "UDW")
        self.assertEqual(target_uplink["speed_mbps"], 2500)

    def test_site_model_keeps_integration_and_internal_namespaces(self):
        sites = _site_records({"data": [{"id": "uuid-123", "internalReference": "default", "name": "Main"}]})
        self.assertEqual(sites, [{"id": "uuid-123", "internal_reference": "default", "name": "Main"}])
        self.assertEqual(_v2_site_path("default", "wan/enriched-configuration"), "/proxy/network/v2/api/site/default/wan/enriched-configuration")
        self.assertEqual(_legacy_site_path("default", "stat/health"), "/proxy/network/api/s/default/stat/health")
        self.assertNotIn("uuid-123", _v2_site_path("default", "topology"))

    def test_missing_internal_reference_never_guesses_default(self):
        sites = _site_records({"data": [{"id": "uuid-123", "name": "Main"}]})
        self.assertEqual(sites, [{"id": "uuid-123", "name": "Main"}])

    def test_unconfirmed_realtime_sla_fields_are_not_projected(self):
        merged = _merge_wans({"data": [{"id": "wan1", "latencyMs": 4, "packetLossPercent": 0, "jitterMs": 1, "uptimeSeconds": 5}]})
        self.assertEqual(merged[0]["role"], "unknown")
        self.assertNotIn("latency_ms", merged[0])
        self.assertNotIn("packet_loss_percent", merged[0])
        self.assertNotIn("jitter_ms", merged[0])
        self.assertNotIn("uptime_seconds", merged[0])

    def test_legacy_target_accepts_exact_external_id_alias(self):
        from unifi_api import _legacy_target
        target = {"id": "target-1"}
        self.assertIsNotNone(_legacy_target({"data": [{"external_id": "target-1", "port_table": []}]}, target))
        self.assertIsNone(_legacy_target({"data": [{"external_id": "other", "name": "target-1"}]}, target))

    def test_port_counter_delta_and_reset_are_bounded(self):
        previous = {}
        base = {"port_idx": 7, "up": True, "speed": 1000, "rx_bytes": 1000, "tx_bytes": 2000}
        first = _port_record(base, device_id="device", previous_samples=previous, sample_time=10.0)
        self.assertNotIn("rx_bps", first)
        second = _port_record({**base, "rx_bytes": 3000, "tx_bytes": 6000}, device_id="device", previous_samples=previous, sample_time=11.0)
        self.assertEqual(second["rx_bps"], 2000)
        self.assertEqual(second["tx_bps"], 4000)
        self.assertEqual(second["rx_utilization_pct"], 0.0)
        reset = _port_record({**base, "rx_bytes": 10, "tx_bytes": 20}, device_id="device", previous_samples=previous, sample_time=12.0)
        self.assertNotIn("rx_bps", reset)

    def test_counter_directions_are_validated_independently(self):
        previous = {}
        base = {"port_idx": 8, "up": True, "speed": 1000, "rx_bytes": 1000, "tx_bytes": 2000}
        _port_record(base, device_id="device", previous_samples=previous, sample_time=10.0)
        item = _port_record({**base, "rx_bytes": 2000, "tx_bytes": 10_000_000_000}, device_id="device", previous_samples=previous, sample_time=11.0)
        self.assertEqual(item["rx_bps"], 1000)
        self.assertIn("rx_utilization_pct", item)
        self.assertNotIn("tx_bps", item)
        self.assertNotIn("tx_utilization_pct", item)

    def test_speed_change_and_invalid_interval_discard_rates(self):
        previous = {}
        base = {"port_idx": 9, "up": True, "speed": 1000, "rx_bytes": 1000, "tx_bytes": 2000}
        _port_record(base, device_id="device", previous_samples=previous, sample_time=10.0)
        changed = _port_record({**base, "speed": 2500, "rx_bytes": 3000, "tx_bytes": 4000}, device_id="device", previous_samples=previous, sample_time=11.0)
        self.assertNotIn("rx_bps", changed)
        invalid_dt = _port_record({**base, "rx_bytes": 4000, "tx_bytes": 5000}, device_id="device", previous_samples=previous, sample_time=10.5)
        self.assertNotIn("rx_bps", invalid_dt)

    def test_port_link_fields_and_poe_active_are_preserved(self):
        item = _port_record({"port_idx": 4, "name": "PoE", "media": "GE", "up": True, "enable": True, "full_duplex": True, "autoneg": True, "is_uplink": False, "speed": 1000, "max_speed": 2500, "port_poe": True, "poe_enable": True, "poe_power": "6.8", "poe_max_power": "30"}, device_id="device", previous_samples={}, sample_time=1.0)
        self.assertEqual(item["media"], "GE")
        self.assertTrue(item["duplex"] and item["autoneg"] and item["enabled"] and item["up"])
        self.assertFalse(item["uplink"])
        self.assertEqual(item["poe"]["power_w"], 6.8)
        self.assertEqual(item["max_speed_mbps"], 2500)
        self.assertEqual(item["poe"]["max_power_w"], 30)
        self.assertTrue(item["poe"]["active"])

    def test_device_reported_poe_total_wins_over_port_sum(self):
        legacy = {"data": [{"device_id": "device", "port_table": [
            {"port_idx": 1, "up": True, "port_poe": True, "poe_power": "4.0"},
            {"port_idx": 2, "up": True, "port_poe": True, "poe_power": "5.0"},
        ]}]}
        records, summary = _ports(legacy, {"id": "device"}, {}, 1.0, {"poe_total_power_w": 20.0, "poe_max_power_w": 420.0})
        self.assertEqual(len(records), 2)
        self.assertEqual(summary["poe_total_power_w"], 20.0)
        self.assertEqual(summary["poe_total_source"], "device_reported")
        self.assertEqual(summary["poe_max_power_w"], 420.0)

    def test_udw_v2_wan_shape_maps_nested_identity_and_top_level_speedtest(self):
        enriched = [
            {"configuration": {"_id": "wan-primary-id", "name": "WAN", "wan_networkgroup": "WAN"},
             "details": {"service_provider": {"name": "Example ISP", "asn": 64500}}},
            {"configuration": {"_id": "wan-backup-id", "name": "WAN2", "wan_networkgroup": "WAN2"},
             "details": {"service_provider": {"name": "Backup ISP", "asn": 64501}}},
        ]
        load_balance = {"wan_interfaces": [
            {"name": "WAN", "state": "ACTIVE", "wan_networkgroup": "WAN"},
            {"name": "WAN2", "state": "BACKUP", "wan_networkgroup": "WAN2"},
        ]}
        isp_status = [
            {"speedtest_historical": [
                {"download_mbps": 900, "interface_name": "WAN", "latency_ms": 2.5,
                 "time": 1704067200, "upload_mbps": 100, "wan_networkgroup": "WAN"},
                {"download_mbps": 910, "interface_name": "WAN", "latency_ms": 2.4,
                 "time": 1704067205, "upload_mbps": 101, "wan_networkgroup": "WAN"},
            ]},
            {"speedtest_historical": [
                {"download_mbps": 300, "interface_name": "WAN2", "latency_ms": 8,
                 "time": 1704067200, "upload_mbps": 40, "wan_networkgroup": "WAN2"},
            ]},
        ]

        self.assertEqual(_network_groups(enriched), ["WAN", "WAN2"])
        result = _merge_wans(enriched, load_balance, isp_status)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "wan-primary-id")
        self.assertEqual(result[0]["isp"], "Example ISP")
        self.assertEqual(result[0]["asn"], "64500")
        self.assertEqual(result[0]["role"], "active")
        self.assertEqual(result[0]["speedtest"]["download_mbps"], 910.0)
        self.assertTrue(result[0]["speedtest"]["timestamp"].startswith("2024-01-01T00:00:05"))
        self.assertEqual(result[1]["id"], "wan-backup-id")
        self.assertEqual(result[1]["role"], "backup")
        self.assertEqual(result[1]["speedtest"]["upload_mbps"], 40.0)
        self.assertEqual(_statistics_wans({"data": [{"model": "UDW", "name": "UDW", "state": "ONLINE"}]}), [])

    def test_wan_merge_preserves_identity_and_historical_speedtest(self):
        result = _merge_wans(
            {"data": [{"id": "wan1", "name": "Primary", "online": True}]},
            {"data": [{"id": "wan1", "role": "active", "asn": 64500, "speedtestHistory": [{"timestamp": "2026-01-01T00:00:00Z", "latencyMs": 2.5, "downloadMbps": 900, "uploadMbps": 100}]}]},
        )
        self.assertEqual(result[0]["name"], "Primary")
        self.assertEqual(result[0]["role"], "active")
        self.assertEqual(result[0]["asn"], "64500")
        self.assertEqual(result[0]["speedtest"]["latency_ms"], 2.5)
        self.assertNotIn("packet_loss_percent", result[0])

    def test_wan_merge_excludes_device_uplink_records(self):
        result = _merge_wans({"data": [
            {"id": "wan1", "name": "WAN1", "networkGroup": "WAN"},
            {"name": "UDW", "model": "UniFi Dream Wall", "state": "ONLINE"},
            {"name": "USW Flex Mini", "model": "USW Flex Mini", "state": "ONLINE"},
        ]})
        self.assertEqual([item.get("id") for item in result], ["wan1"])

    def test_down_port_does_not_emit_rates_or_utilization(self):
        previous = {}
        _port_record({"port_idx": 1, "up": False, "speed": 1000, "rx_bytes": 10, "tx_bytes": 20}, device_id="device", previous_samples=previous, sample_time=1.0)
        item = _port_record({"port_idx": 1, "up": False, "speed": 1000, "rx_bytes": 100, "tx_bytes": 200}, device_id="device", previous_samples=previous, sample_time=2.0)
        self.assertNotIn("rx_bps", item)
        self.assertNotIn("tx_utilization_pct", item)

    def test_poe_missing_is_not_fabricated(self):
        item = _port_record({"port_idx": 2, "up": True, "speed": 1000}, device_id="device", previous_samples={}, sample_time=1.0)
        self.assertNotIn("poe", item)
        item = _port_record({"port_idx": 3, "up": True, "speed": 1000, "port_poe": False, "poe_power": "0.00"}, device_id="device", previous_samples={}, sample_time=1.0)
        self.assertEqual(item["poe"]["supported"], False)
        self.assertNotIn("power_w", item["poe"])

    def test_multiple_sites_fail_closed_without_selector(self):
        calls = []
        sites = [{"id": "site-a", "name": "A"}, {"id": "site-b", "name": "B"}]
        result = UniFiAPICollector(self.config, request=self._fixture_request(calls, sites=sites), target_profile="udw").collect()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["error"]["code"], "api_partial_failure")
        sites_endpoint = next(item for item in result["endpoints"] if item["name"] == "sites")
        self.assertEqual(sites_endpoint["error"]["code"], "api_site_ambiguity")
        self.assertFalse(any(path.endswith("/devices") for path in calls))

    def test_explicit_site_selector_is_deterministic(self):
        calls = []
        sites = [{"id": "site-a", "name": "A"}, {"id": "site-b", "name": "B"}]
        self.config.site_id = "site-b"
        result = UniFiAPICollector(self.config, request=self._fixture_request(calls, sites=sites), target_profile="udw").collect()
        self.assertEqual(result["status"], "available")
        self.assertIsNone(result["error"])
        self.assertIn("/proxy/network/integration/v1/sites/site-b/devices", calls)
        self.assertFalse(any("/proxy/network/v2/api/site/" in path for path in calls))

    def test_target_resolution_does_not_depend_on_device_order(self):
        calls = []
        devices = [
            {"id": "ap-1", "model": "U6", "name": "AP", "state": "ONLINE"},
            {"id": "udw-1", "model": "UDW", "name": "UDW", "state": "ONLINE"},
            {"id": "switch-1", "model": "USW", "name": "Switch", "state": "ONLINE"},
        ]
        result = UniFiAPICollector(self.config, request=self._fixture_request(calls, devices=devices), target_profile="udw").collect()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["error"]["code"], "api_partial_failure")
        self.assertEqual(result["telemetry"]["identity"]["model"], "UDW")

    def test_missing_target_is_explicit_error(self):
        calls = []
        devices = [{"id": "ap-1", "model": "U6", "name": "AP", "state": "ONLINE"}]
        result = UniFiAPICollector(self.config, request=self._fixture_request(calls, devices=devices), target_profile="udw").collect()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["error"]["code"], "api_partial_failure")
        self.assertEqual(next(item for item in result["endpoints"] if item["name"] == "devices")["error"]["code"], "api_target_resolution")

    def test_optional_endpoint_failure_is_partial_capability_not_global_error(self):
        calls = []
        result = UniFiAPICollector(self.config, request=self._fixture_request(calls, fail="/clients"), target_profile="udw").collect()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["error"]["code"], "api_partial_failure")
        self.assertEqual(next(item for item in result["endpoints"] if item["name"] == "clients")["status"], "unsupported")
        self.assertIsNotNone(result["telemetry"]["devices"])

    def test_required_auth_failure_is_unavailable(self):
        result = UniFiAPICollector(self.config, request=lambda config, path, key: (_ for _ in ()).throw(APIError("api_auth_failure", status=401)), target_profile="udw").collect()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["error"]["code"], "api_auth_failure")
        self.assertEqual(result["error"]["http_status"], 401)

    def test_api_endpoint_registry_has_no_root_resources(self):
        self.assertEqual(API_ENDPOINTS, (
            ("info", "/proxy/network/integration/v1/info"),
            ("sites", "/proxy/network/integration/v1/sites"),
        ))


if __name__ == "__main__":
    unittest.main()
