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

    def test_linux_device_v2_passes_normalized_hardware_config_to_collector(self):
        from multi_device_contracts import (
            ClientV2Config,
            FilesystemProbeConfig,
            SmartDeviceConfig,
        )

        namespace = runpy.run_path(str(CLIENT_DIR / "client-linux.py"))
        captured = {}

        class CapturingCollector(object):
            def __init__(self, **kwargs):
                captured.update(kwargs)

        config = ClientV2Config(
            server_url="https://status.example.invalid",
            device_id="device-alpha",
            device_name=None,
            device_fqdn=None,
            token_file="/run/secrets/token",
            smart_devices=(SmartDeviceConfig("/dev/sda", "sat", "disk one"),),
            primary_smart_device="/dev/sda",
            filesystem_probes=(FilesystemProbeConfig("/", "/host-storage/root"),),
        )
        with mock.patch.dict(
            namespace["_device_v2_extension_collector"].__globals__,
            {
                "HostExtensionCollector": CapturingCollector,
                "collect_client_build": lambda protocol: {
                    "version": "2.3-preview-test",
                    "revision": "a" * 40,
                    "build_time": "2026-08-11T00:00:00Z",
                    "protocol": protocol,
                },
            },
        ):
            namespace["_device_v2_extension_collector"](config, ["synthetic"])
        self.assertEqual(captured["smart_devices"], [{"path": "/dev/sda", "type": "sat", "label": "disk one"}])
        self.assertEqual(captured["primary_smart_device"], "/dev/sda")
        self.assertEqual(captured["filesystem_probes"], [{"mountpoint": "/", "probe_path": "/host-storage/root"}])
        self.assertEqual(captured["client_build"]["protocol"], "device_v2")
        self.assertEqual(captured["easytier_args"], ["synthetic"])

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
