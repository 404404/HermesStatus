import json
import sys
import unittest
from pathlib import Path


CLIENT_DIR = Path(__file__).resolve().parent
ROOT = CLIENT_DIR.parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from multi_device_contracts import (  # noqa: E402
    ClientContractError,
    RecordingMockTransport,
    build_envelope,
    parse_config_json,
    resolve_client_config,
    retry_delay_seconds,
    validate_server_url,
)


class ClientV2ConfigContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = (
            ROOT
            / "testdata"
            / "multi_device"
            / "valid"
            / "client-v2-config.json"
        ).read_text(encoding="utf-8")
        self.file_values = parse_config_json(self.fixture)

    def test_strict_file_parser_and_safe_defaults(self):
        config = resolve_client_config(file_values=self.file_values)
        self.assertEqual(config.server_url, "https://status.example.invalid")
        self.assertTrue(config.verify_tls)
        self.assertEqual(config.connect_timeout_seconds, 10)
        self.assertEqual(config.read_timeout_seconds, 30)
        self.assertEqual(config.collection_interval_seconds, 60)
        self.assertEqual(config.smart_devices[0].path, "/dev/disk+1")
        self.assertEqual(config.primary_smart_device, "/dev/disk+1")
        self.assertEqual(config.filesystem_probes[0].probe_path, "/host-storage/data")

        document = json.loads(self.fixture)
        document["DOMAIN"] = "ambiguous.example.invalid"
        with self.assertRaises(ClientContractError):
            parse_config_json(json.dumps(document))

    def test_checked_in_manual_client_example_uses_the_real_parser(self):
        example = (
            ROOT / "config" / "examples" / "client-v2.example.json"
        ).read_text(encoding="utf-8")
        config = resolve_client_config(file_values=parse_config_json(example))
        self.assertEqual(config.device_id, "compute-01")
        self.assertEqual(config.server_url, "https://status.example.invalid")
        self.assertTrue(config.verify_tls)
        self.assertEqual(
            config.token_file,
            "/run/secrets/hermesstatus-device-token",
        )

    def test_cli_over_env_over_file_over_defaults(self):
        config = resolve_client_config(
            file_values=self.file_values,
            env={
                "HERMESSTATUS_SERVER_URL": "https://env.example.invalid",
                "HERMESSTATUS_DEVICE_NAME": "Synthetic Env",
                "HERMESSTATUS_CONNECT_TIMEOUT_SECONDS": "20",
            },
            cli={
                "server_url": "https://cli.example.invalid",
                "device_name": "Synthetic CLI",
            },
        )
        self.assertEqual(config.server_url, "https://cli.example.invalid")
        self.assertEqual(config.device_name, "Synthetic CLI")
        self.assertEqual(config.connect_timeout_seconds, 20)
        self.assertEqual(config.read_timeout_seconds, 30)

    def test_partial_v2_fails_closed_without_legacy_fallback(self):
        with self.assertRaisesRegex(ClientContractError, "incomplete v2"):
            resolve_client_config(
                env={"HERMESSTATUS_SERVER_URL": "https://status.example.invalid"}
            )
        with self.assertRaises(ClientContractError):
            resolve_client_config(
                env={
                    "SERVER": "legacy.example.invalid",
                    "USER": "synthetic-user",
                    "PASSWORD": "synthetic-plaintext-value",
                }
            )

    def test_url_rejects_credentials_query_fragment_path_and_insecure_http(self):
        invalid = [
            "https://synthetic-user@status.example.invalid",
            "https://status.example.invalid?device=x",
            "https://status.example.invalid#fragment",
            "https://status.example.invalid/prefix",
            "https://status.example.invalid\\unexpected",
            "http://status.example.invalid",
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ClientContractError):
                validate_server_url(
                    value, verify_tls=True, loopback_test_profile=False
                )

    def test_loopback_http_requires_explicit_test_profile(self):
        self.assertEqual(
            validate_server_url(
                "http://127.0.0.1",
                verify_tls=False,
                loopback_test_profile=True,
            ),
            "http://127.0.0.1",
        )
        with self.assertRaises(ClientContractError):
            validate_server_url(
                "http://127.0.0.1",
                verify_tls=False,
                loopback_test_profile=False,
            )
        with self.assertRaises(ClientContractError):
            validate_server_url(
                "http://status.example.invalid",
                verify_tls=False,
                loopback_test_profile=True,
            )

    def test_plaintext_token_and_unknown_options_do_not_exist(self):
        for source in ({"token": "synthetic-value"}, {"password": "synthetic-value"}):
            with self.subTest(source=source), self.assertRaises(ClientContractError):
                resolve_client_config(file_values=self.file_values, cli=source)
        with self.assertRaises(ClientContractError):
            resolve_client_config(
                file_values={**self.file_values, "unknown": "synthetic"}
            )

    def test_unifi_schema_matches_the_strict_file_backed_contract(self):
        schema = json.loads((CLIENT_DIR.parent / "schemas" / "client-v2-config.schema.json").read_text(encoding="utf-8"))
        unifi = schema["properties"]["unifi"]
        self.assertEqual(len(unifi["oneOf"]), 2)
        disabled, enabled = unifi["oneOf"]
        self.assertFalse(disabled["properties"]["enabled"]["const"])
        self.assertTrue(enabled["properties"]["enabled"]["const"])
        self.assertFalse(enabled["additionalProperties"])
        self.assertEqual(enabled["properties"]["profile"]["enum"], ["udw", "ucg-max"])
        self.assertNotIn("command", enabled["properties"])
        self.assertNotIn("password", enabled["properties"])

    def test_unifi_configuration_is_strict_and_credential_file_only(self):
        unifi = {
            "enabled": True, "profile": "udw", "host": "192.0.2.1", "port": 22,
            "username": "root", "credential_file": "/run/secrets/unifi-password",
            "known_hosts_file": "/run/secrets/unifi-known-hosts",
            "connect_timeout_seconds": 10, "interval_seconds": 60,
        }
        config = resolve_client_config(file_values={**self.file_values, "unifi": unifi})
        self.assertEqual(config.unifi.profile_id, "udw")
        self.assertEqual(config.unifi.interval_seconds, 60)
        for mutation in ({**unifi, "command": "id"}, {**unifi, "profile": "unknown"}, {**unifi, "host": "192.0.2.1;id"}, {"enabled": False, "profile": "udw"}):
            with self.subTest(mutation=mutation), self.assertRaises(ClientContractError):
                resolve_client_config(file_values={**self.file_values, "unifi": mutation})

    def test_fqdn_device_id_timeout_and_token_path_validation(self):
        mutations = [
            {"device_id": "INVALID ID"},
            {"device_fqdn": "192.0.2.10"},
            {"connect_timeout_seconds": 0},
            {"read_timeout_seconds": 301},
            {"collection_interval_seconds": 9},
            {"token_file": "relative/token"},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(
                ClientContractError
            ):
                resolve_client_config(file_values={**self.file_values, **mutation})


class ClientV2MockTests(unittest.TestCase):
    def setUp(self):
        values = parse_config_json(
            (
                ROOT
                / "testdata"
                / "multi_device"
                / "valid"
                / "client-v2-config.json"
            ).read_text(encoding="utf-8")
        )
        self.config = resolve_client_config(file_values=values)

    def test_envelope_builder_has_no_credentials(self):
        stats = {
            "cpu": 12,
            "extension_version": "1.0-draft",
            "hardware": {"error": {"code": "timeout", "message": "unavailable"}},
            "docker": {},
            "hermes": {},
            "lucky": {},
        }
        envelope = build_envelope(
            self.config,
            collected_at="2026-07-01T12:00:00Z",
            hostname="synthetic-alpha",
            stats=stats,
        )
        encoded = json.dumps(envelope).lower()
        self.assertNotIn("authorization", encoded)
        self.assertNotIn("token_file", encoded)
        self.assertNotIn("/run/secrets", encoded)
        self.assertEqual(envelope["device"]["id"], "device-alpha")
        self.assertEqual(envelope["stats"], stats)

    def test_envelope_forbidden_fields_time_and_size(self):
        for field in ("token", "config", "command", "device_json", "lucky_json"):
            with self.subTest(field=field), self.assertRaises(ClientContractError):
                build_envelope(
                    self.config,
                    collected_at="2026-07-01T12:00:00Z",
                    stats={field: "synthetic-forbidden"},
                )
        with self.assertRaises(ClientContractError):
            build_envelope(
                self.config,
                collected_at="2026-07-01 12:00:00",
                stats={"extension_version": "1.0-draft"},
            )
        with self.assertRaises(ClientContractError):
            build_envelope(
                self.config,
                collected_at="2026-07-01T12:00:00Z",
                stats={"custom": "x" * (1 << 20)},
            )

    def test_retry_schedule_is_pure_bounded_and_resets_by_attempt(self):
        values = [
            retry_delay_seconds(attempt, jitter_fraction=1.0)
            for attempt in range(12)
        ]
        self.assertEqual(values[0], 3.0)
        self.assertEqual(values[-1], 300.0)
        self.assertTrue(all(left <= right for left, right in zip(values, values[1:])))
        self.assertEqual(retry_delay_seconds(0, jitter_fraction=0.5), 1.5)

    def test_recording_transport_performs_no_network_io(self):
        transport = RecordingMockTransport(
            {
                "accepted": True,
                "server_time": "2026-07-01T12:00:00Z",
                "config_generation": "synthetic-generation",
                "monitors": [],
            }
        )
        envelope = build_envelope(
            self.config,
            collected_at="2026-07-01T12:00:00Z",
            stats={
                "extension_version": "1.0-draft",
                "hardware": {},
                "docker": {},
                "hermes": {},
                "lucky": {},
            },
        )
        response = transport.send("/api/v2/device-updates", envelope)
        self.assertTrue(response["accepted"])
        self.assertEqual(len(transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
