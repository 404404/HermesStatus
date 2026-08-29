import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

CLIENT_DIR = Path(__file__).resolve().parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from client_config_v1 import materialize_unified_collectors
from multi_device_contracts import ClientContractError, parse_config_json, resolve_client_config


def document():
    return {
        "schema_version": 1,
        "server": {
            "url": "https://status.example.invalid:21443",
            "verify_tls": True,
            "connect_timeout_seconds": 10,
            "read_timeout_seconds": 30,
            "ca_file": "/run/secrets/preview-ca.crt",
        },
        "device": {"id": "gk50", "display_name": "GK50", "platform": "linux"},
        "collection": {"interval_seconds": 30},
        "collectors": {
            "hardware": {"enabled": True},
            "filesystem": {"enabled": True, "probes": [
                {"mountpoint": "/home/hermes", "probe_path": "/home/hermes"},
            ]},
            "smart": {"enabled": True, "devices": [{"path": "/dev/sda"}], "primary_device": "/dev/sda"},
            "docker": {"enabled": True},
            "hermes": {"enabled": True},
            "lucky": {
                "enabled": True, "base_url": "http://127.0.0.1:16601",
                "auth_mode": "open_token", "verify_tls": True,
                "timeout_seconds": 5, "warning_days": 30,
                "version_check_ttl": 21600, "open_token": "synthetic-token",
            },
            "easytier": {
                "enabled": True, "cli_path": "/usr/local/bin/easytier-cli",
                "rpc_portal": "127.0.0.1:15888", "timeout_seconds": 5,
                "interval_seconds": 30, "administrative_role": "site_router",
            },
            "unifi": {"enabled": False},
        },
    }


class UnifiedClientConfigTests(unittest.TestCase):
    def test_strict_schema_and_mapping(self):
        config = resolve_client_config(file_values=parse_config_json(json.dumps(document())))
        self.assertEqual(config.device_id, "gk50")
        self.assertEqual(config.collection_interval_seconds, 30)
        self.assertEqual(config.token_file, "/run/secrets/hermesstatus-device-token")
        self.assertEqual(config.filesystem_probes[0].probe_path, "/home/hermes")
        self.assertTrue(config.unified_collectors["lucky"]["enabled"])

    def test_unknown_fields_and_version_fail_closed(self):
        value = document()
        value["unexpected"] = True
        with self.assertRaises(ClientContractError):
            parse_config_json(json.dumps(value))
        value = document()
        value["schema_version"] = 2
        with self.assertRaises(ClientContractError):
            parse_config_json(json.dumps(value))

    def test_disabled_collectors_have_no_target_fields(self):
        value = document()
        value["collectors"]["filesystem"] = {"enabled": False, "probes": []}
        with self.assertRaises(ClientContractError):
            parse_config_json(json.dumps(value))
        value["collectors"]["filesystem"] = {"enabled": True, "probes": []}
        value["collectors"]["lucky"] = {"enabled": False}
        config = resolve_client_config(file_values=parse_config_json(json.dumps(value)))
        self.assertFalse(config.unified_collectors["lucky"]["enabled"])

    def test_materialize_secrets_uses_private_files(self):
        parsed = parse_config_json(json.dumps(document()))
        with tempfile.TemporaryDirectory() as tmp:
            runtime = materialize_unified_collectors(parsed["unified_collectors"], tmp)
            token_path = runtime["lucky"]["token_file"]
            self.assertEqual(Path(token_path).read_text(), "synthetic-token")
            self.assertTrue(stat.S_IMODE(os.stat(token_path).st_mode) == 0o600)
            self.assertFalse(Path(token_path).is_symlink()
            )
        self.assertFalse(Path(token_path).exists())

    def test_source_and_path_allowlist(self):
        value = document()
        value["collectors"]["easytier"]["cli_path"] = "/bin/sh"
        with self.assertRaises(ClientContractError):
            parse_config_json(json.dumps(value))

    def test_api_only_unifi_configuration_is_rejected(self):
        value = document()
        value["collectors"]["unifi"] = {
            "enabled": True, "profile": "udw", "host": "192.0.2.1", "port": 22,
            "interval_seconds": 60, "ssh": {"enabled": False},
            "api": {"enabled": True, "base_url": "https://192.0.2.1", "api_key": "key", "tls_sha256": "a" * 64, "timeout_seconds": 5},
        }
        with self.assertRaises(ClientContractError):
            parse_config_json(json.dumps(value))

    def test_unifi_with_no_enabled_transport_is_rejected(self):
        value = document()
        value["collectors"]["unifi"] = {
            "enabled": True, "profile": "udw", "host": "192.0.2.1", "port": 22,
            "interval_seconds": 60,
            "ssh": {"enabled": False},
            "api": {"enabled": False},
        }
        with self.assertRaises(ClientContractError):
            parse_config_json(json.dumps(value))

    def test_hardware_cannot_be_disabled_with_storage_collectors(self):
        value = document()
        value["collectors"]["hardware"] = {"enabled": False}
        with self.assertRaises(ClientContractError):
            parse_config_json(json.dumps(value))

    def test_malformed_unifi_api_port_is_rejected(self):
        value = document()
        value["collectors"]["unifi"] = {
            "enabled": True, "profile": "udw", "host": "192.0.2.1", "port": 22,
            "interval_seconds": 60,
            "ssh": {"enabled": True, "username": "root", "password": "secret", "known_hosts": ["192.0.2.1 ssh-ed25519 AAAA"], "port": 22},
            "api": {"enabled": True, "base_url": "https://192.0.2.1:bad", "api_key": "key", "tls_sha256": "a" * 64, "timeout_seconds": 5},
        }
        with self.assertRaises(ClientContractError):
            parse_config_json(json.dumps(value))
        value = document()
        value["collectors"]["filesystem"]["probes"][0]["probe_path"] = "/tmp/../etc"
        with self.assertRaises(ClientContractError):
            parse_config_json(json.dumps(value))


if __name__ == "__main__":
    unittest.main()
