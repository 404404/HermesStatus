import importlib.util
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


CLIENT_DIR = Path(__file__).resolve().parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))


class ClientArgumentTests(unittest.TestCase):

    def test_device_v2_clients_pass_normalized_hardware_config_to_collector(self):
        if "psutil" not in sys.modules and importlib.util.find_spec("psutil") is None:
            sys.modules["psutil"] = types.ModuleType("psutil")
        from multi_device_contracts import (
            ClientV2Config,
            FilesystemProbeConfig,
            SmartDeviceConfig,
            UniFiConfig,
        )

        unifi = UniFiConfig(
            profile_id="udw",
            host="192.0.2.1",
            port=22,
            username="root",
            credential_file="/run/secrets/unifi-password",
            known_hosts_file="/run/secrets/unifi-known-hosts",
            connect_timeout_seconds=10,
            interval_seconds=60,
        )
        config = ClientV2Config(
            server_url="https://status.example.invalid",
            device_id="device-alpha",
            device_name=None,
            device_fqdn=None,
            token_file="/run/secrets/token",
            smart_devices=(SmartDeviceConfig("/dev/sda", "sat", "disk one"),),
            primary_smart_device="/dev/sda",
            filesystem_probes=(FilesystemProbeConfig("/", "/host-storage/root"),),
            unifi=unifi,
        )
        for filename in ("client-linux.py", "client-psutil.py"):
            with self.subTest(client=filename):
                namespace = runpy.run_path(str(CLIENT_DIR / filename))
                captured = {}

                class CapturingCollector(object):
                    def __init__(self, **kwargs):
                        captured.update(kwargs)

                with mock.patch.dict(
                    namespace["_device_v2_extension_collector"].__globals__,
                    {
                        "HostExtensionCollector": CapturingCollector,
                        "collect_client_build": lambda protocol: {
                            "version": "2.5-test",
                            "revision": "a" * 40,
                            "build_time": "2026-08-11T00:00:00Z",
                            "protocol": protocol,
                        },
                        "UniFiDomainCollector": lambda value: {"profile": value.profile_id},
                    },
                ):
                    namespace["_device_v2_extension_collector"](config, ["synthetic"])
                self.assertEqual(captured["smart_devices"], [{"path": "/dev/sda", "type": "sat", "label": "disk one"}])
                self.assertEqual(captured["primary_smart_device"], "/dev/sda")
                self.assertEqual(captured["filesystem_probes"], [{"mountpoint": "/", "probe_path": "/host-storage/root"}])
                self.assertEqual(captured["client_build"]["protocol"], "device_v2")
                self.assertEqual(captured["easytier_args"], ["synthetic"])
                self.assertEqual(captured["unifi_collector"], {"profile": "udw"})

    def test_password_with_user_text_does_not_replace_username(self):
        if "psutil" not in sys.modules and importlib.util.find_spec("psutil") is None:
            sys.modules["psutil"] = types.ModuleType("psutil")

        arguments = [
            "SERVER=127.0.0.1",
            "PORT=35601",
            "USER=s01",
            "PASSWORD=USER_DEFAULT_PASSWORD",
            "INTERVAL=2",
            "NOTUSER=ignored",
        ]
        expected = {
            "SERVER": "127.0.0.1",
            "PORT": "35601",
            "USER": "s01",
            "PASSWORD": "USER_DEFAULT_PASSWORD",
            "INTERVAL": "2",
        }

        for filename in ("client-linux.py", "client-psutil.py"):
            with self.subTest(client=filename):
                namespace = runpy.run_path(str(CLIENT_DIR / filename))
                self.assertEqual(namespace["parse_cli_args"](arguments), expected)

    def test_both_clients_use_the_same_device_v2_protocol_owners(self):
        if "psutil" not in sys.modules and importlib.util.find_spec("psutil") is None:
            sys.modules["psutil"] = types.ModuleType("psutil")
        namespaces = [
            runpy.run_path(str(CLIENT_DIR / filename))
            for filename in ("client-linux.py", "client-psutil.py")
        ]
        for shared_name in (
            "load_client_selection",
            "create_device_v2_runner",
            "install_monitor_definitions",
        ):
            self.assertIs(
                namespaces[0][shared_name],
                namespaces[1][shared_name],
                f"{shared_name} was duplicated between Client entrypoints",
            )
        self.assertIsNot(
            namespaces[0]["_device_v2_stats_collector"],
            namespaces[1]["_device_v2_stats_collector"],
        )

    def test_carrier_latency_probe_surface_is_removed(self):
        legacy_probe_terms = (
            "ping_10010",
            "ping_189",
            "ping_10086",
            "time_10010",
            "time_189",
            "time_10086",
            "cu.tz.cloudcpp.com",
            "ct.tz.cloudcpp.com",
            "cm.tz.cloudcpp.com",
            "PROBEPORT",
            "PROBE_PROTOCOL_PREFER",
            "PING_PACKET_HISTORY_LEN",
        )
        # The Device v2 input validator keeps a narrow transitional allowlist so
        # deployed 2.3 clients can update a 2.5 server.  Public collection,
        # schema, model, API, and UI surfaces must remain free of these fields.
        paths = (
            CLIENT_DIR / "client-linux.py",
            CLIENT_DIR / "client-psutil.py",
            CLIENT_DIR / "multi_device_contracts.py",
            CLIENT_DIR.parent / "Dockerfile.client",
            CLIENT_DIR.parent / "docker-compose-client.yml",
            CLIENT_DIR.parent / "schemas" / "device-update-v2.schema.json",
            CLIENT_DIR.parent / "schemas" / "stats-v2.schema.json",
            CLIENT_DIR.parent / "server" / "model.go",
            CLIENT_DIR.parent / "server" / "app.go",
            CLIENT_DIR.parent / "server" / "extension_openapi.go",
        )
        for path in paths:
            content = path.read_text(encoding="utf-8")
            for term in legacy_probe_terms:
                with self.subTest(path=path.name, term=term):
                    self.assertNotIn(term, content)

    def test_client_image_does_not_force_legacy_transport_into_v2_mode(self):
        dockerfile = (CLIENT_DIR.parent / "Dockerfile.client").read_text(
            encoding="utf-8"
        )
        for legacy_default in (
            "ENV SERVER=",
            "SERVERSTATUS_USER=s01",
            "USER=s01",
            "PORT=35601",
            "PASSWORD=",
        ):
            self.assertNotIn(legacy_default, dockerfile)
        compose = (
            CLIENT_DIR.parent / "docker-compose-client.yml"
        ).read_text(encoding="utf-8")
        for legacy_key in ("SERVER:", "SERVERSTATUS_USER:", "PASSWORD:", "PORT:"):
            self.assertIn(legacy_key, compose)


if __name__ == "__main__":
    unittest.main()
