import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "config" / "examples"


class ManualDeviceExampleTests(unittest.TestCase):
    def test_json_examples_are_synthetic_and_contain_no_plaintext_token(self):
        registry = json.loads(
            (EXAMPLES / "device-registry.example.json").read_text(
                encoding="utf-8"
            )
        )
        client = json.loads(
            (EXAMPLES / "client-v2.example.json").read_text(encoding="utf-8")
        )
        mapping = json.loads(
            (EXAMPLES / "legacy-device-mapping.example.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(registry["devices"]), 3)
        self.assertIsNone(registry["devices"][0]["expected_fqdn"])
        self.assertEqual(client["device"]["id"], "compute-01")
        self.assertEqual(mapping["mappings"][0]["device_id"], "legacy-01")
        for path in EXAMPLES.rglob("*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn('"token":', text)
            self.assertNotIn('"password":', text)
            self.assertNotIn('"authorization":', text.lower())
            self.assertNotIn("BEGIN PRIVATE KEY", text)

    def test_server_override_mounts_authority_read_only_and_hides_backend(self):
        path = EXAMPLES / "docker-compose-server.override.example.yml"
        source = path.read_text(encoding="utf-8")
        document = yaml.safe_load(source.replace("!reset ", ""))
        service = document["services"]["serverstatus-server"]
        environment = service["environment"]
        self.assertEqual(
            environment["DEVICE_REGISTRY_PATH"],
            "/etc/hermesstatus/devices.json",
        )
        self.assertEqual(
            environment["HERMESSTATUS_DEVICE_CREDENTIALS_DIR"],
            "/etc/hermesstatus/credentials.d",
        )
        self.assertEqual(
            environment["LEGACY_DEVICE_MAPPING_PATH"],
            "/etc/hermesstatus/legacy-device-mapping.json",
        )
        volumes = service["volumes"]
        self.assertTrue(
            all(volume.endswith(":ro") for volume in volumes[:3])
        )
        self.assertFalse(volumes[3].endswith(":ro"))
        self.assertIn("ports: !reset []", source)

    def test_client_override_removes_legacy_transport_and_mounts_v2_read_only(self):
        source = (
            EXAMPLES / "docker-compose-client.override.example.yml"
        ).read_text(encoding="utf-8")
        document = yaml.safe_load(source.replace("!override", ""))
        service = document["services"]["serverstatus-client"]
        for key in ("SERVER", "SERVERSTATUS_USER", "USER", "PORT", "PASSWORD"):
            self.assertNotIn(key, service["environment"])
        self.assertIn("environment: !override", source)
        self.assertTrue(
            all(volume.endswith(":ro") for volume in service["volumes"])
        )
        base = yaml.safe_load(
            (ROOT / "docker-compose-client.yml").read_text(encoding="utf-8")
        )["services"]["serverstatus-client"]
        self.assertTrue(base["read_only"])
        self.assertIn("no-new-privileges:true", base["security_opt"])
        self.assertIn("/tmp:size=32m,mode=1777,nosuid,nodev,noexec", base["tmpfs"])

    def test_reverse_proxy_is_an_exact_bounded_tls_ingress(self):
        source = (
            EXAMPLES / "reverse-proxy.nginx.example.conf"
        ).read_text(encoding="utf-8")
        for required in (
            "location = /api/v2/device-updates",
            "limit_except POST",
            "ssl_protocols TLSv1.2 TLSv1.3",
            "ssl_early_data off",
            "client_max_body_size 1m",
            "large_client_header_buffers 4 8k",
            "client_header_timeout 10s",
            "client_body_timeout 15s",
            "proxy_connect_timeout 5s",
            "proxy_send_timeout 15s",
            "proxy_read_timeout 30s",
            'proxy_set_header Forwarded "for=$remote_addr;proto=https"',
            "proxy_set_header X-Forwarded-For $remote_addr",
            "proxy_cache off",
            'add_header Cache-Control "no-store" always',
            "location /",
            "return 404",
        ):
            self.assertIn(required, source)
        log_format = source.split("upstream", 1)[0].lower()
        self.assertNotIn("authorization", log_format)
        self.assertNotIn("request_body", log_format)
        self.assertNotIn("return 30", source)


if __name__ == "__main__":
    unittest.main()
