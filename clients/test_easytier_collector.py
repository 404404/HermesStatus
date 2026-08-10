import json
import os
import stat
import tempfile
import unittest

from easytier_collector import EasyTierCollector, load_easytier_config, not_configured_easytier


class Result(object):
    def __init__(self, value, returncode=0):
        self.stdout = json.dumps(value).encode("utf-8")
        self.returncode = returncode


class Runner(object):
    def __init__(self, failures=()):
        self.failures = set(failures)
        self.calls = []

    def __call__(self, argv, **kwargs):
        command = tuple(argv[-2:])
        self.calls.append((list(argv), kwargs))
        if command in self.failures:
            return Result({}, 1)
        values = {
            ("node", "info"): {
                "instance_name": "fixture-node", "network_name": "fixture-net",
                "version": "2.6.4", "peer_id": 12345,
                "public_endpoint": "https://must-not-appear.example",
            },
            ("peer", "list"): [
                {"id": 12345, "connection_type": "direct"},
                {"id": 54321, "connection_type": "direct"},
                {"id": 67890, "connection_type": "relay"}
            ],
            ("route", "list"): [{"id": 12345}, {"id": 54321}],
            ("connector", "list"): [{"protocol": "tcp", "connected": True}],
            ("stats", "show"): {
                "traffic_bytes_rx": 101, "traffic_bytes_tx": 202,
                "traffic_bytes_forwarded": 303, "secret": "must-not-appear",
            },
        }
        return Result(values[command])


class EasyTierCollectorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.cli = os.path.join(self.directory.name, "easytier-cli")
        with open(self.cli, "w", encoding="utf-8") as handle:
            handle.write("fixture")
        os.chmod(self.cli, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        self.environ = {
            "EASYTIER_ENABLED": "true", "EASYTIER_CLI_PATH": self.cli,
            "EASYTIER_RPC_PORTAL": "127.0.0.1:15888",
        }

    def tearDown(self):
        self.directory.cleanup()

    def test_disabled_is_safe_not_configured(self):
        payload = not_configured_easytier()
        self.assertEqual(payload["status"], "not_configured")
        self.assertIsNone(payload["updated_at"])
        self.assertEqual(set(payload["command_status"]), {"node_info", "peer_list", "route_list", "connector_list", "stats_show"})

    def test_collects_only_allowlisted_sanitized_projection(self):
        runner = Runner()
        payload = EasyTierCollector(environ=self.environ, runner=runner).collect()
        self.assertEqual(payload["status"], "healthy")
        self.assertEqual(payload["node"]["instance_name"], "fixture-node")
        self.assertIsNone(payload["node"].get("public_endpoint"))
        self.assertEqual(payload["peers"], {"total": 2, "direct": 1, "relay": 1, "unknown_path": 0})
        self.assertEqual(payload["routes"]["total"], 1)
        self.assertTrue(payload["connectors"]["tcp_configured"])
        self.assertEqual(payload["traffic"]["bytes_forwarded"], 303)
        self.assertNotIn("secret", json.dumps(payload))
        self.assertEqual(len(runner.calls), 5)
        for argv, kwargs in runner.calls:
            self.assertEqual(argv[:5], [self.cli, "-p", "127.0.0.1:15888", "-o", "json"])
            self.assertFalse(kwargs["shell"])
            self.assertIsNotNone(kwargs["stderr"])

    def test_preserves_node_network_name_and_only_marks_tcp_as_active(self):
        class NonTCPRunner(Runner):
            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                if tuple(argv[-2:]) == ("connector", "list"):
                    return Result([{"protocol": "udp", "connected": True}])
                return result

        payload = EasyTierCollector(environ=self.environ, runner=NonTCPRunner()).collect()
        self.assertEqual(payload["node"]["network_name"], "fixture-net")
        self.assertFalse(payload["connectors"]["tcp_configured"])
        self.assertFalse(payload["connectors"]["tcp_active"])

    def test_partial_failure_is_degraded_and_does_not_leak_stderr(self):
        payload = EasyTierCollector(environ=self.environ, runner=Runner({("peer", "list")})).collect()
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["command_status"]["peer_list"]["status"], "unavailable")
        self.assertEqual(payload["error"]["code"], "partial_failure")
        self.assertNotIn("stderr", json.dumps(payload))

    def test_rejects_non_loopback_and_symlink_cli(self):
        invalid = dict(self.environ, EASYTIER_RPC_PORTAL="10.250.250.1:15888")
        with self.assertRaises(ValueError):
            load_easytier_config(environ=invalid)
        link = os.path.join(self.directory.name, "link")
        os.symlink(self.cli, link)
        payload = EasyTierCollector(environ=dict(self.environ, EASYTIER_CLI_PATH=link), runner=Runner()).collect()
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["error"]["code"], "easytier_cli_unavailable")

    def test_cli_precedence_over_environment_and_json(self):
        config = os.path.join(self.directory.name, "config.json")
        with open(config, "w", encoding="utf-8") as handle:
            json.dump({"enabled": False, "interval_seconds": 45}, handle)
        os.chmod(config, stat.S_IRUSR | stat.S_IWUSR)
        config = load_easytier_config(
            ["--easytier-enabled", "true", "--easytier-interval-seconds", "60"],
            dict(self.environ, EASYTIER_CONFIG_FILE=config, EASYTIER_INTERVAL_SECONDS="50"),
        )
        self.assertTrue(config["enabled"])
        self.assertEqual(config["interval_seconds"], 60)


if __name__ == "__main__":
    unittest.main()
