import json
import os
import stat
import subprocess
import tempfile
import unittest

from easytier_collector import EasyTierCollector, _command_duration_ms, load_easytier_config, not_configured_easytier


class Result(object):
    def __init__(self, value, returncode=0):
        self.stdout = json.dumps(value).encode("utf-8")
        self.returncode = returncode


def stats(rx=101, tx=202, instance_rx=31, instance_tx=41):
    return [
        {"name": "traffic_bytes_rx", "value": rx, "labels": {"network_name": "home"}},
        {"name": "traffic_bytes_tx", "value": tx, "labels": {"network_name": "home"}},
        {"name": "traffic_bytes_forwarded", "value": 303, "labels": {"network_name": "home"}},
        {"name": "traffic_packets_rx", "value": 11, "labels": {"network_name": "home"}},
        {"name": "traffic_packets_tx", "value": 12, "labels": {"network_name": "home"}},
        {"name": "traffic_bytes_rx_by_instance", "value": instance_rx, "labels": {"network_name": "home", "from_instance_id": "remote"}},
        {"name": "traffic_bytes_tx_by_instance", "value": instance_tx, "labels": {"network_name": "home", "to_instance_id": "remote"}},
        {"name": "traffic_packets_rx_by_instance", "value": 3, "labels": {"network_name": "home", "from_instance_id": "remote"}},
        {"name": "traffic_packets_tx_by_instance", "value": 4, "labels": {"network_name": "home", "to_instance_id": "remote"}},
        {"name": "peer_rpc_client_rx", "value": 1, "labels": {"network_name": "home", "method_name": "first"}},
        {"name": "peer_rpc_client_rx", "value": 2, "labels": {"network_name": "home", "method_name": "second"}},
    ]


class Runner(object):
    def __init__(self, failures=(), stats_values=None):
        self.failures = set(failures)
        self.calls = []
        self.stats_values = list(stats_values or [stats()])
        self.stats_index = 0

    def __call__(self, argv, **kwargs):
        command = tuple(argv[5:])
        self.calls.append((list(argv), kwargs))
        if command in self.failures:
            raise subprocess.TimeoutExpired(argv, 5)
        if command == ("stats",):
            value = self.stats_values[min(self.stats_index, len(self.stats_values) - 1)]
            self.stats_index += 1
            return Result(value)
        values = {
            ("node",): {
                "hostname": "fixture-node", "inst_id": "fixture-instance", "version": "2.6.4-8428a89d",
                "peer_id": 12345, "ipv4_addr": "10.250.250.1/24", "proxy_cidrs": ["192.168.68.0/24"],
                "listeners": ["udp://[::]:11010", "https://bad.example:443/path"],
                "stun_info": {"udp_nat_type": "OpenInternet", "tcp_nat_type": "Unknown", "public_ip": ["203.0.113.10"], "last_update_time": "2026-08-23T12:00:00Z"},
                "config": {"network_secret": "must-not-appear"},
            },
            ("peer",): [
                {"id": 12345, "cidr": "10.250.250.1/24", "ipv4": "10.250.250.1", "cost": "Local", "lat_ms": "-", "loss_rate": "-", "rx_bytes": "0 B", "tx_bytes": "0 B", "tunnel_proto": "", "nat_type": "Unknown", "version": "2.6.4"},
                {"id": 54321, "cidr": "10.250.250.2/24", "ipv4": "10.250.250.2", "hostname": "remote", "cost": "p2p", "lat_ms": "10.09", "loss_rate": "0.0%", "rx_bytes": "814.06 kB", "tx_bytes": "6.97 MB", "tunnel_proto": "tcp6,udp", "nat_type": "Cone", "version": "2.6.4"},
            ],
            ("route",): [
                {"ipv4": "10.250.250.1/24", "hostname": "fixture-node", "next_hop_hostname": "Local", "path_latency": 0, "path_len": 0, "proxy_cidrs": ["192.168.68.0/24"], "version": "2.6.4"},
                {"ipv4": "10.250.250.2/24", "hostname": "remote", "next_hop_hostname": "remote", "path_latency": 10, "path_len": 1, "proxy_cidrs": ["192.168.88.0/24"], "version": "2.6.4"},
            ],
            ("connector",): [{"url": {"url": "udp://bootstrap.example:11010"}, "status": 0}],
        }
        return Result(values[command])


class IncrementClock(object):
    def __init__(self):
        self.value = 0

    def __call__(self):
        self.value += 1
        return self.value


class EasyTierCollectorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.cli = os.path.join(self.directory.name, "easytier-cli")
        with open(self.cli, "w", encoding="utf-8") as handle:
            handle.write("fixture")
        os.chmod(self.cli, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        self.environ = {"EASYTIER_ENABLED": "true", "EASYTIER_CLI_PATH": self.cli, "EASYTIER_RPC_PORTAL": "127.0.0.1:15888"}

    def tearDown(self):
        self.directory.cleanup()

    def test_disabled_is_safe_not_configured(self):
        payload = not_configured_easytier()
        self.assertEqual(payload["status"], "not_configured")
        self.assertEqual(set(payload["command_status"]), {"node_info", "peer_list", "route_list", "connector_list", "stats_show"})

    def test_collects_five_stable_sources_and_drops_node_config(self):
        runner = Runner()
        payload = EasyTierCollector(environ=self.environ, runner=runner).collect()
        self.assertEqual(payload["status"], "healthy")
        self.assertEqual([call[0][5:] for call in runner.calls], [["node"], ["peer"], ["route"], ["connector"], ["stats"]])
        self.assertEqual(payload["command_status"]["route_list"]["status"], "healthy")
        self.assertEqual(payload["routes"]["items"][1]["next_hop_peer_id"], "remote")
        self.assertEqual(payload["node"]["hostname"], "fixture-node")
        self.assertEqual(payload["node"]["listeners"], ["udp://[::]:11010"])
        self.assertNotIn("config", payload["node"])
        self.assertNotIn("network_secret", json.dumps(payload))
        self.assertNotIn("must-not-appear", json.dumps(payload))

    def test_peer_connector_and_empty_connector_semantics(self):
        payload = EasyTierCollector(environ=self.environ, runner=Runner()).collect()
        self.assertEqual(payload["peers"]["total"], 1)
        peer = payload["peers"]["items"][0]
        self.assertEqual(peer["cost"], "p2p")
        self.assertEqual(peer["established_tunnels"], ["tcp6", "udp"])
        self.assertEqual(peer["rx_display"], "814.06 kB")
        self.assertEqual(payload["connectors"]["items"][0]["status"], "connected")
        class EmptyConnectorRunner(Runner):
            def __call__(self, argv, **kwargs):
                if tuple(argv[5:]) == ("connector",):
                    self.calls.append((list(argv), kwargs))
                    return Result([])
                return super().__call__(argv, **kwargs)
        empty = EasyTierCollector(environ=self.environ, runner=EmptyConnectorRunner()).collect()
        self.assertEqual(empty["connectors"]["total"], 0)
        self.assertEqual(empty["status"], "healthy")

    def test_local_peer_is_excluded_from_remote_peer_aggregates(self):
        class SingleNodeRunner(Runner):
            def __call__(self, argv, **kwargs):
                if tuple(argv[5:]) == ("peer",):
                    self.calls.append((list(argv), kwargs))
                    return Result([{
                        "id": 12345, "ipv4": "10.250.250.1", "cost": "Local",
                        "rx_bytes": "0 B", "tx_bytes": "0 B",
                    }])
                return super().__call__(argv, **kwargs)

        payload = EasyTierCollector(environ=self.environ, runner=SingleNodeRunner()).collect()
        self.assertEqual(payload["command_status"]["peer_list"]["status"], "healthy")
        self.assertEqual(payload["peers"]["items"], [])
        self.assertEqual(payload["peers"]["total"], 0)
        self.assertEqual(payload["peers"]["direct"], 0)
        self.assertEqual(payload["peers"]["relay"], 0)
        self.assertEqual(payload["peers"]["unknown_path"], 0)
        self.assertIsNone(payload["peers"]["ipv6_udp_direct"])

    def test_local_marker_is_excluded_when_node_info_is_unavailable(self):
        payload = EasyTierCollector(
            environ=self.environ,
            runner=Runner({("node",)}),
        ).collect()
        self.assertEqual(payload["command_status"]["node_info"]["status"], "unavailable")
        self.assertEqual(payload["command_status"]["peer_list"]["status"], "healthy")
        self.assertEqual(payload["peers"]["total"], 1)
        self.assertEqual(payload["peers"]["items"][0]["peer_id"], "54321")

    def test_unknown_connector_status_is_not_guessed(self):
        class UnknownConnectorRunner(Runner):
            def __call__(self, argv, **kwargs):
                if tuple(argv[5:]) == ("connector",):
                    self.calls.append((list(argv), kwargs))
                    return Result([{"url": {"url": "udp://bootstrap.example:11010"}, "status": 7}])
                return super().__call__(argv, **kwargs)
        payload = EasyTierCollector(environ=self.environ, runner=UnknownConnectorRunner()).collect()
        self.assertEqual(payload["connectors"]["items"][0]["raw_status"], 7)
        self.assertEqual(payload["connectors"]["items"][0]["status"], "unknown")

    def test_stats_keep_name_plus_labels_and_compute_rates(self):
        runner = Runner(stats_values=[stats(100, 200), stats(160, 260)])
        collector = EasyTierCollector(environ=self.environ, runner=runner, clock=IncrementClock())
        first = collector.collect()
        second = collector.collect()
        self.assertIsNone(first["traffic"]["rx_bps"])
        self.assertGreater(second["traffic"]["rx_bps"], 0)
        rpc = [item for item in second["traffic"]["samples"] if item["name"] == "peer_rpc_client_rx"]
        self.assertEqual({item["labels"]["method_name"] for item in rpc}, {"first", "second"})
        self.assertEqual(second["traffic"]["by_instance"][0]["from_instance_id"], "remote")

    def test_counter_reset_reports_rate_unavailable(self):
        collector = EasyTierCollector(environ=self.environ, runner=Runner(stats_values=[stats(100, 200), stats(10, 20)]), clock=IncrementClock())
        collector.collect()
        payload = collector.collect()
        self.assertIsNone(payload["traffic"]["rx_bps"])
        self.assertIsNone(payload["traffic"]["tx_bps"])

    def test_timeout_and_malformed_command_are_partial_not_global_failure(self):
        payload = EasyTierCollector(environ=self.environ, runner=Runner({("peer",)})).collect()
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["command_status"]["peer_list"]["status"], "unavailable")
        self.assertEqual(payload["node"]["state"], "running")
        class MalformedRunner(Runner):
            def __call__(self, argv, **kwargs):
                if tuple(argv[5:]) == ("stats",):
                    self.calls.append((list(argv), kwargs))
                    return Result({"unexpected": 1})
                return super().__call__(argv, **kwargs)
        malformed = EasyTierCollector(environ=self.environ, runner=MalformedRunner()).collect()
        self.assertEqual(malformed["status"], "degraded")
        self.assertEqual(malformed["command_status"]["stats_show"]["status"], "invalid_data")
        route_timeout = EasyTierCollector(environ=self.environ, runner=Runner({("route",)})).collect()
        self.assertEqual(route_timeout["status"], "degraded")
        self.assertEqual(route_timeout["command_status"]["route_list"]["status"], "unavailable")
        self.assertEqual(route_timeout["routes"]["items"], [])

    def test_command_duration_and_secure_configuration(self):
        self.assertEqual(_command_duration_ms(0, 30.001), 30000)
        self.assertEqual(_command_duration_ms(2, 1), 0)
        with self.assertRaises(ValueError):
            load_easytier_config(environ=dict(self.environ, EASYTIER_RPC_PORTAL="10.250.250.1:15888"))
        link = os.path.join(self.directory.name, "link")
        os.symlink(self.cli, link)
        self.assertEqual(EasyTierCollector(environ=dict(self.environ, EASYTIER_CLI_PATH=link), runner=Runner()).collect()["status"], "unavailable")

    def test_empty_optional_administrative_role_is_not_invalid_configuration(self):
        config = load_easytier_config(environ=dict(self.environ, EASYTIER_ADMINISTRATIVE_ROLE=""))
        self.assertIsNone(config["administrative_role"])

    def test_administrative_role_is_explicit_config_not_node_config(self):
        payload = EasyTierCollector(
            environ=dict(self.environ, EASYTIER_ADMINISTRATIVE_ROLE="site_router"),
            runner=Runner(),
        ).collect()
        self.assertEqual(payload["node"]["administrative_role"], "site_router")
        with self.assertRaises(ValueError):
            load_easytier_config(environ=dict(self.environ, EASYTIER_ADMINISTRATIVE_ROLE="invalid"))


if __name__ == "__main__":
    unittest.main()
