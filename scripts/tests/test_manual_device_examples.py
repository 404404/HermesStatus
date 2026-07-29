import json
import unittest
from pathlib import Path

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
        runtime = json.loads(
            (ROOT / "testdata" / "server-runtime-synthetic.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(registry["devices"]), 4)
        self.assertFalse(registry["devices"][3]["enabled"])
        self.assertIsNone(registry["devices"][0]["expected_fqdn"])
        self.assertEqual(client["device"]["id"], "compute-01")
        self.assertEqual(mapping["mappings"][0]["device_id"], "legacy-01")
        self.assertEqual(
            runtime["servers"][0]["username"],
            "synthetic-legacy-01",
        )
        self.assertEqual(
            runtime["servers"][0]["password"],
            "USER_DEFAULT_PASSWORD",
        )
        self.assertEqual(runtime["monitors"], [])
        self.assertEqual(runtime["sslcerts"], [])
        for path in EXAMPLES.rglob("*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn('"token":', text)
            self.assertNotIn('"password":', text)
            self.assertNotIn('"authorization":', text.lower())
            self.assertNotIn("BEGIN PRIVATE KEY", text)

    def test_server_override_mounts_authority_read_only_and_hides_backend(self):
        path = EXAMPLES / "docker-compose-server.override.example.yml"
        source = path.read_text(encoding="utf-8")
        for required in (
            "DEVICE_REGISTRY_PATH: /etc/hermesstatus/devices.json",
            "HERMESSTATUS_DEVICE_CREDENTIALS_DIR: /etc/hermesstatus/credentials.d",
            "LEGACY_DEVICE_MAPPING_PATH: /etc/hermesstatus/legacy-device-mapping.json",
            "./device-registry.example.json:/etc/hermesstatus/devices.json:ro",
            "./credentials.d:/etc/hermesstatus/credentials.d:ro",
            "./legacy-device-mapping.example.json:/etc/hermesstatus/legacy-device-mapping.json:ro",
            "./state:/var/lib/hermesstatus",
            "ports: !reset []",
        ):
            self.assertIn(required, source)
        self.assertNotIn("./state:/var/lib/hermesstatus:ro", source)

    def test_client_override_removes_legacy_transport_and_mounts_v2_read_only(self):
        source = (
            EXAMPLES / "docker-compose-client.override.example.yml"
        ).read_text(encoding="utf-8")
        environment = source.split("environment: !override", 1)[1].split(
            "volumes:",
            1,
        )[0]
        for key in ("SERVER", "SERVERSTATUS_USER", "USER", "PORT", "PASSWORD"):
            self.assertNotIn(f"{key}:", environment)
        self.assertIn("environment: !override", source)
        for required in (
            "./client-v2.example.json:/etc/hermesstatus/client-v2.json:ro",
            "./compute-01.token:/run/secrets/hermesstatus-device-token:ro",
        ):
            self.assertIn(required, source)
        base = (ROOT / "docker-compose-client.yml").read_text(encoding="utf-8")
        self.assertIn("read_only: true", base)
        self.assertIn("no-new-privileges:true", base)
        self.assertIn("/tmp:size=32m,mode=1777,nosuid,nodev,noexec", base)

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
