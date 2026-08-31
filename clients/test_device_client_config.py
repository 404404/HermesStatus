import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


CLIENT_DIR = Path(__file__).resolve().parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from device_client_config import (  # noqa: E402
    ClientMode,
    load_client_selection,
    load_custom_ca,
    load_device_token,
)
from multi_device_contracts import ClientContractError, resolve_client_config  # noqa: E402


TOKEN = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


class DeviceClientConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.token_path = self.root / "device.token"
        self.token_path.write_text(TOKEN, encoding="utf-8")
        self.token_path.chmod(0o600)
        self.complete_env = {
            "HERMESSTATUS_SERVER_URL": "https://status.example.invalid",
            "HERMESSTATUS_DEVICE_ID": "device-alpha",
            "HERMESSTATUS_DEVICE_NAME": "Synthetic Alpha",
            "HERMESSTATUS_DEVICE_FQDN": "alpha.example.invalid",
            "HERMESSTATUS_DEVICE_TOKEN_FILE": str(self.token_path),
            "HERMESSTATUS_TLS_VERIFY": "true",
            "HERMESSTATUS_CONNECT_TIMEOUT_SECONDS": "10",
            "HERMESSTATUS_READ_TIMEOUT_SECONDS": "30",
            "HERMESSTATUS_COLLECTION_INTERVAL_SECONDS": "60",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_legacy_default_and_complete_v2_are_explicit(self):
        legacy = load_client_selection([], environ={"SERVER": "127.0.0.1"})
        self.assertIs(legacy.mode, ClientMode.LEGACY)

        legacy_with_build_metadata = load_client_selection(
            [],
            environ={
                "SERVER": "127.0.0.1",
                "HERMESSTATUS_CLIENT_VERSION": "2.5",
                "HERMESSTATUS_CLIENT_REVISION": "abcdef012345",
            },
        )
        self.assertIs(legacy_with_build_metadata.mode, ClientMode.LEGACY)

        v2 = load_client_selection([], environ=self.complete_env)
        self.assertIs(v2.mode, ClientMode.DEVICE_V2)
        self.assertEqual(v2.device_v2.device_id, "device-alpha")

    def test_catalog_build_metadata_alone_does_not_select_device_v2(self):
        metadata = {
            "HERMESSTATUS_CLIENT_VERSION": "2.7",
            "HERMESSTATUS_CLIENT_REVISION": "e" * 40,
            "HERMESSTATUS_CLIENT_BUILD_TIME": "2026-08-31T00:00:00Z",
            "HERMESSTATUS_CLIENT_PROTOCOL": "device_v2",
            "HERMESSTATUS_UNIFI_CATALOG_REVISION": "a" * 40,
            "HERMESSTATUS_UNIFI_CATALOG_SCHEMA_VERSION": "1",
            "HERMESSTATUS_UNIFI_CATALOG_SHA256": "b" * 64,
        }
        selection = load_client_selection([], environ=metadata)
        self.assertIs(selection.mode, ClientMode.LEGACY)
        self.assertIsNone(selection.device_v2)

    def test_valid_device_v2_configuration_is_unchanged_by_catalog_metadata(self):
        baseline = load_client_selection([], environ=self.complete_env)
        with_metadata = load_client_selection(
            [],
            environ={
                **self.complete_env,
                "HERMESSTATUS_CLIENT_VERSION": "2.7",
                "HERMESSTATUS_CLIENT_REVISION": "e" * 40,
                "HERMESSTATUS_CLIENT_BUILD_TIME": "2026-08-31T00:00:00Z",
                "HERMESSTATUS_CLIENT_PROTOCOL": "device_v2",
                "HERMESSTATUS_UNIFI_CATALOG_REVISION": "a" * 40,
                "HERMESSTATUS_UNIFI_CATALOG_SCHEMA_VERSION": "1",
                "HERMESSTATUS_UNIFI_CATALOG_SHA256": "b" * 64,
            },
        )
        self.assertIs(with_metadata.mode, ClientMode.DEVICE_V2)
        self.assertEqual(with_metadata.device_v2, baseline.device_v2)

    def test_cli_over_environment_over_file_over_defaults(self):
        config_path = self.root / "client.json"
        config_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "server": {
                        "url": "https://file.example.invalid",
                        "verify_tls": True,
                        "connect_timeout_seconds": 7,
                        "read_timeout_seconds": 20,
                    },
                    "device": {
                        "id": "device-alpha",
                        "name": "File",
                        "fqdn": "alpha.example.invalid",
                        "token_file": str(self.token_path),
                    },
                    "collection": {"interval_seconds": 120},
                }
            ),
            encoding="utf-8",
        )
        config_path.chmod(0o600)
        selection = load_client_selection(
            [
                "HERMESSTATUS_SERVER_URL=https://cli.example.invalid",
                "HERMESSTATUS_DEVICE_NAME=CLI",
            ],
            environ={
                "HERMESSTATUS_CONFIG_FILE": str(config_path),
                "HERMESSTATUS_SERVER_URL": "https://env.example.invalid",
                "HERMESSTATUS_DEVICE_NAME": "Environment",
                "HERMESSTATUS_READ_TIMEOUT_SECONDS": "25",
            },
        )
        config = selection.device_v2
        self.assertEqual(config.server_url, "https://cli.example.invalid")
        self.assertEqual(config.device_name, "CLI")
        self.assertEqual(config.read_timeout_seconds, 25)
        self.assertEqual(config.connect_timeout_seconds, 7)
        self.assertEqual(config.collection_interval_seconds, 120)

    def test_hardware_json_config_is_normalized_and_cli_overrides_env_and_file(self):
        config_path = self.root / "hardware-client.json"
        config_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "server": {
                        "url": "https://file.example.invalid",
                        "verify_tls": True,
                        "connect_timeout_seconds": 7,
                        "read_timeout_seconds": 20,
                    },
                    "device": {
                        "id": "device-alpha", "name": "File",
                        "fqdn": None, "token_file": str(self.token_path),
                    },
                    "collection": {"interval_seconds": 120},
                    "hardware": {
                        "smart_devices": [{"path": "/dev/sda", "type": "sat"}],
                        "primary_smart_device": "/dev/sda",
                        "filesystem_probes": [{
                            "mountpoint": "/volume1", "probe_path": "/host-storage/volume1",
                        }],
                    },
                }
            ),
            encoding="utf-8",
        )
        config_path.chmod(0o600)
        selection = load_client_selection(
            [
                'HERMESSTATUS_SMART_DEVICES=[{"path":"/dev/nvme0n1","type":"nvme"}]',
                "HERMESSTATUS_PRIMARY_SMART_DEVICE=/dev/nvme0n1",
            ],
            environ={
                "HERMESSTATUS_CONFIG_FILE": str(config_path),
                "SMART_DEVICES": '[{"path":"/dev/sdb"}]',
                "PRIMARY_SMART_DEVICE": "/dev/sdb",
            },
        )
        config = selection.device_v2
        self.assertEqual(config.smart_devices[0].path, "/dev/nvme0n1")
        self.assertEqual(config.smart_devices[0].type, "nvme")
        self.assertEqual(config.primary_smart_device, "/dev/nvme0n1")
        self.assertEqual(config.filesystem_probes[0].mountpoint, "/volume1")

    def test_hardware_config_rejects_unsafe_device_and_probe_paths(self):
        for hardware in (
            {"smart_devices": [{"path": "/dev/../sda"}]},
            {"filesystem_probes": [{"mountpoint": "/", "probe_path": "relative"}]},
        ):
            document = {
                "version": 1,
                "server": {
                    "url": "https://file.example.invalid", "verify_tls": True,
                    "connect_timeout_seconds": 7, "read_timeout_seconds": 20,
                },
                "device": {
                    "id": "device-alpha", "name": None, "fqdn": None,
                    "token_file": str(self.token_path),
                },
                "collection": {"interval_seconds": 120}, "hardware": hardware,
            }
            path = self.root / ("invalid-%s.json" % len(hardware))
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.subTest(hardware=hardware), self.assertRaises(ClientContractError):
                load_client_selection([], environ={"HERMESSTATUS_CONFIG_FILE": str(path)})

    def test_filesystem_mountpoint_keeps_spacing_and_matches_wire_bound(self):
        preserved = resolve_client_config(
            env=self.complete_env,
            file_values={"filesystem_probes": [{
                "mountpoint": "/mnt/My  Drive", "probe_path": "/host-storage/data",
            }]},
        )
        self.assertEqual(preserved.filesystem_probes[0].mountpoint, "/mnt/My  Drive")
        too_long = "/" + "a" * 512
        with self.assertRaises(ClientContractError):
            resolve_client_config(
                env=self.complete_env,
                file_values={"filesystem_probes": [{
                    "mountpoint": too_long, "probe_path": "/host-storage/data",
                }]},
            )

    def test_device_v2_treats_legacy_auto_as_a_discovery_sentinel(self):
        automatic = resolve_client_config(
            env={**self.complete_env, "SMART_DEVICE": "auto"},
        )
        self.assertIsNone(automatic.smart_devices)

        explicit_empty = resolve_client_config(
            env={**self.complete_env, "SMART_DEVICE": "auto"},
            file_values={"smart_devices": []},
        )
        self.assertEqual(explicit_empty.smart_devices, ())

    def test_unknown_catalog_and_arbitrary_metadata_names_still_fail_closed(self):
        for key in (
            "HERMESSTATUS_UNIFI_CATALOG_UNKNOWN_FIELD",
            "HERMESSTATUS_UNKNOWN_CONFIGURATION",
        ):
            with self.subTest(key=key), self.assertRaises(ClientContractError):
                load_client_selection([], environ={key: "value"})

    def test_build_metadata_is_not_valid_device_v2_cli_configuration(self):
        for key, value in (
            ("HERMESSTATUS_CLIENT_VERSION", "2.7"),
            ("HERMESSTATUS_UNIFI_CATALOG_REVISION", "a" * 40),
            ("HERMESSTATUS_UNIFI_CATALOG_SCHEMA_VERSION", "1"),
            ("HERMESSTATUS_UNIFI_CATALOG_SHA256", "b" * 64),
        ):
            with self.subTest(key=key), self.assertRaises(ClientContractError):
                load_client_selection([f"{key}={value}"], environ={})

    def test_partial_unknown_malformed_and_mixed_v2_fail_closed(self):
        invalid_environments = [
            {"HERMESSTATUS_SERVER_URL": "https://status.example.invalid"},
            {**self.complete_env, "HERMESSTATUS_UNKNOWN": "value"},
            {**self.complete_env, "HERMESSTATUS_TLS_VERIFY": "maybe"},
            {**self.complete_env, "HERMESSTATUS_READ_TIMEOUT_SECONDS": "3.5"},
            {**self.complete_env, "SERVER": "legacy.example.invalid"},
            {**self.complete_env, "PASSWORD": "legacy-placeholder"},
        ]
        for environment in invalid_environments:
            with self.subTest(environment=set(environment)), self.assertRaises(
                ClientContractError
            ):
                load_client_selection([], environ=environment)
        with self.assertRaises(ClientContractError):
            load_client_selection(
                ["HERMESSTATUS_DEVICE_TOKEN=plaintext-value"],
                environ={},
            )
        with self.assertRaises(ClientContractError):
            load_client_selection(
                ["HERMESSTATUS_SERVER_URL=https://status.example.invalid", "USER=s01"],
                environ={},
            )

    def test_unified_config_requires_private_owner_controlled_file(self):
        path = self.root / "private-config.json"
        path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        path.chmod(0o644)
        with self.assertRaises(ClientContractError):
            load_client_selection([], environ={"HERMESSTATUS_CONFIG_FILE": str(path)})

    def test_strict_config_file_and_symlink_boundary(self):
        valid_document = {
            "version": 1,
            "server": {
                "url": "https://status.example.invalid",
                "verify_tls": True,
                "connect_timeout_seconds": 10,
                "read_timeout_seconds": 30,
            },
            "device": {
                "id": "device-alpha",
                "name": None,
                "fqdn": None,
                "token_file": str(self.token_path),
            },
            "collection": {"interval_seconds": 60},
        }
        for name, content in [
            ("unknown", json.dumps({**valid_document, "DOMAIN": "invalid"})),
            ("trailing", json.dumps(valid_document) + "{}"),
            (
                "duplicate",
                json.dumps(valid_document).replace(
                    '"version": 1',
                    '"version": 1, "version": 1',
                    1,
                ),
            ),
        ]:
            path = self.root / f"{name}.json"
            path.write_text(content, encoding="utf-8")
            with self.subTest(name=name), self.assertRaises(ClientContractError):
                load_client_selection(
                    [],
                    environ={"HERMESSTATUS_CONFIG_FILE": str(path)},
                )

        real_path = self.root / "valid.json"
        real_path.write_text(json.dumps(valid_document), encoding="utf-8")
        link_path = self.root / "config-link.json"
        link_path.symlink_to(real_path)
        with self.assertRaises(ClientContractError):
            load_client_selection(
                [],
                environ={"HERMESSTATUS_CONFIG_FILE": str(link_path)},
            )


class DeviceTokenFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write_token(self, name, data, mode=0o600):
        path = self.root / name
        path.write_bytes(data)
        path.chmod(mode)
        return path

    def test_0400_0600_and_one_line_ending_are_accepted(self):
        for name, suffix, mode in [
            ("plain", b"", 0o400),
            ("lf", b"\n", 0o600),
            ("crlf", b"\r\n", 0o600),
        ]:
            path = self.write_token(name, TOKEN.encode() + suffix, mode)
            with self.subTest(name=name):
                self.assertEqual(load_device_token(str(path)), TOKEN)

    def test_unsafe_token_files_and_values_are_rejected_without_secret_leak(self):
        cases = {
            "world-readable": (TOKEN.encode(), 0o644),
            "empty": (b"", 0o600),
            "whitespace": (b" " * 43, 0o600),
            "short": (b"x" * 42, 0o600),
            "long": (b"x" * 44, 0o600),
            "multiple-lines": (TOKEN.encode() + b"\n\n", 0o600),
            "embedded-control": (b"x" * 41 + b"\t" + b"y", 0o600),
            "non-ascii": (b"x" * 42 + b"\xff", 0o600),
            "padding": (b"x" * 42 + b"=", 0o600),
            "dot": (b"x" * 42 + b".", 0o600),
        }
        for name, (data, mode) in cases.items():
            path = self.write_token(name, data, mode)
            with self.subTest(name=name):
                with self.assertRaises(ClientContractError) as captured:
                    load_device_token(str(path))
                self.assertNotIn(TOKEN, str(captured.exception))
                self.assertNotIn(str(path), str(captured.exception))

        directory = self.root / "directory"
        directory.mkdir()
        with self.assertRaises(ClientContractError):
            load_device_token(str(directory))
        with self.assertRaises(ClientContractError):
            load_device_token("relative.token")
        with self.assertRaises(ClientContractError):
            load_device_token(str(self.root / ".." / "device.token"))

        target = self.write_token("target", TOKEN.encode())
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(ClientContractError):
            load_device_token(str(link))
        owned = self.write_token("wrong-owner", TOKEN.encode())
        with mock.patch(
            "device_client_config.os.geteuid",
            return_value=os.geteuid() + 1,
        ), self.assertRaises(ClientContractError):
            load_device_token(str(owned))

    def test_custom_ca_rejects_symlink_and_binary_content(self):
        ca = self.root / "ca.pem"
        ca.write_text("synthetic CA data", encoding="ascii")
        self.assertEqual(load_custom_ca(str(ca)), "synthetic CA data")
        link = self.root / "ca-link.pem"
        link.symlink_to(ca)
        with self.assertRaises(ClientContractError):
            load_custom_ca(str(link))
        binary = self.root / "binary-ca.pem"
        binary.write_bytes(b"\x00" + b"x" * 32)
        with self.assertRaises(ClientContractError):
            load_custom_ca(str(binary))

    def test_config_token_and_ca_reject_symlinked_parent_components(self):
        real = self.root / "real"
        real.mkdir()
        linked = self.root / "linked"
        linked.symlink_to(real, target_is_directory=True)

        token = real / "device.token"
        token.write_text(TOKEN, encoding="ascii")
        token.chmod(0o600)
        with self.assertRaises(ClientContractError):
            load_device_token(str(linked / "device.token"))

        ca = real / "ca.pem"
        ca.write_text("synthetic CA data", encoding="ascii")
        with self.assertRaises(ClientContractError):
            load_custom_ca(str(linked / "ca.pem"))

        config = real / "client.json"
        config.write_text(
            json.dumps(
                {
                    "version": 1,
                    "server": {
                        "url": "https://status.example.invalid",
                        "verify_tls": True,
                        "connect_timeout_seconds": 10,
                        "read_timeout_seconds": 30,
                    },
                    "device": {
                        "id": "device-alpha",
                        "name": None,
                        "fqdn": None,
                        "token_file": str(token),
                    },
                    "collection": {"interval_seconds": 60},
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ClientContractError):
            load_client_selection(
                [],
                environ={
                    "HERMESSTATUS_CONFIG_FILE": str(linked / "client.json"),
                },
            )


if __name__ == "__main__":
    unittest.main()
