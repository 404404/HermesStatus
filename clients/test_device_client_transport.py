import email.message
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path


CLIENT_DIR = Path(__file__).resolve().parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from device_client_transport import (  # noqa: E402
    DeviceHTTPSClient,
    DeviceTransportError,
    DeviceV2Runner,
    MonitorCache,
    install_monitor_definitions,
)
from multi_device_contracts import (  # noqa: E402
    ClientContractError,
    ClientV2Config,
    build_envelope,
    validate_success_response,
)


TOKEN = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


class FakeSocket:
    def __init__(self):
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout


class FakeResponse:
    def __init__(
        self,
        status=202,
        body=b"",
        content_type="application/json",
        extra_headers=None,
        read_error=None,
    ):
        self.status = status
        self.body = body
        self.read_error = read_error
        self.headers = email.message.Message()
        if content_type is not None:
            self.headers.add_header("Content-Type", content_type)
        for key, value in extra_headers or []:
            self.headers.add_header(key, value)

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, _limit):
        if self.read_error is not None:
            raise self.read_error
        return self.body


class FakeConnection:
    def __init__(self, response=None, connect_error=None):
        self.response = response
        self.connect_error = connect_error
        self.sock = FakeSocket()
        self.requests = []
        self.closed = False

    def connect(self):
        if self.connect_error is not None:
            raise self.connect_error

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, dict(headers or {})))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def success_document(monitors=None):
    return {
        "accepted": True,
        "server_time": "2026-07-01T12:00:00Z",
        "config_generation": "g-42",
        "monitors": [] if monitors is None else monitors,
    }


def success_response(monitors=None):
    return FakeResponse(body=json.dumps(success_document(monitors)).encode())


def valid_stats(cpu=12):
    return {
        "cpu": cpu,
        "extension_version": "1.0-draft",
        "hardware": {},
        "docker": {},
        "hermes": {},
        "lucky": {},
    }


class DeviceTransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.token_path = self.root / "token"
        self.token_path.write_text(TOKEN, encoding="utf-8")
        self.token_path.chmod(0o600)
        self.config = ClientV2Config(
            server_url="https://status.example.invalid",
            device_id="device-alpha",
            device_name="Synthetic Alpha",
            device_fqdn="alpha.example.invalid",
            token_file=str(self.token_path),
            verify_tls=True,
            connect_timeout_seconds=7,
            read_timeout_seconds=19,
            collection_interval_seconds=60,
        )
        self.envelope = build_envelope(
            self.config,
            collected_at="2026-07-01T12:00:00Z",
            stats=valid_stats(),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def client_for(self, connection):
        return DeviceHTTPSClient(
            self.config,
            connection_factory=lambda _config, _context: connection,
        )

    def test_fixed_request_headers_body_and_timeouts(self):
        connection = FakeConnection(success_response())
        client = self.client_for(connection)
        response = client.send(self.envelope)
        self.assertTrue(response["accepted"])
        self.assertEqual(connection.sock.timeout, 19)
        self.assertTrue(connection.closed)
        self.assertEqual(len(connection.requests), 1)
        method, path, body, headers = connection.requests[0]
        self.assertEqual((method, path), ("POST", "/api/v2/device-updates"))
        self.assertEqual(
            set(headers),
            {
                "Content-Type",
                "Accept",
                "Authorization",
                "X-HermesStatus-Device-ID",
            },
        )
        self.assertEqual(headers["Authorization"], "Bearer " + TOKEN)
        self.assertEqual(headers["X-HermesStatus-Device-ID"], "device-alpha")
        decoded = json.loads(body)
        self.assertEqual(decoded["device"]["id"], "device-alpha")
        encoded = body.decode()
        self.assertNotIn("token_file", encoded)
        self.assertNotIn(TOKEN, encoded)
        self.assertNotIn("password", encoded.lower())
        self.assertNotIn("command", encoded.lower())
        self.assertNotIn(TOKEN, repr(client))

    def test_local_identity_mismatch_is_never_sent(self):
        connection = FakeConnection(success_response())
        client = self.client_for(connection)
        wrong = dict(self.envelope)
        wrong["device"] = {"id": "device-beta"}
        with self.assertRaisesRegex(DeviceTransportError, "local_identity_mismatch"):
            client.send(wrong)
        self.assertEqual(connection.requests, [])

        injected = dict(self.envelope)
        injected["authorization"] = "synthetic-forbidden"
        with self.assertRaisesRegex(DeviceTransportError, "payload_incompatible"):
            client.send(injected)
        self.assertEqual(connection.requests, [])

    def test_status_classification_and_bounded_retry_after(self):
        cases = [
            (400, "payload_incompatible", None, []),
            (401, "authorization_rejected", None, []),
            (403, "authorization_rejected", None, []),
            (404, "endpoint_unavailable", None, []),
            (413, "payload_too_large", None, []),
            (415, "protocol_incompatible", None, []),
            (429, "rate_limited", 45.0, [("Retry-After", "45")]),
            (429, "rate_limited", None, [("Retry-After", "999999")]),
            (500, "server_unavailable", None, []),
            (302, "redirect_rejected", None, [("Location", "https://other.invalid")]),
        ]
        for status, code, retry_after, headers in cases:
            with self.subTest(status=status, headers=headers):
                client = self.client_for(
                    FakeConnection(
                        FakeResponse(status=status, body=b"secret-response", extra_headers=headers)
                    )
                )
                with self.assertRaises(DeviceTransportError) as captured:
                    client.send(self.envelope)
                self.assertEqual(captured.exception.code, code)
                self.assertEqual(
                    captured.exception.retry_after_seconds,
                    retry_after,
                )
                self.assertNotIn("secret-response", str(captured.exception))

    def test_conflict_codes_are_bounded_and_redacted(self):
        for code in ("stale_report", "report_conflict"):
            response = FakeResponse(
                status=409,
                body=json.dumps(
                    {
                        "error": {
                            "code": code,
                            "request_id": "req-synthetic",
                        }
                    }
                ).encode(),
            )
            with self.assertRaises(DeviceTransportError) as captured:
                self.client_for(FakeConnection(response)).send(self.envelope)
            self.assertEqual(captured.exception.code, code)
        hostile = FakeResponse(
            status=409,
            body=b'{"error":{"code":"secret-value","request_id":"req"}}',
        )
        with self.assertRaises(DeviceTransportError) as captured:
            self.client_for(FakeConnection(hostile)).send(self.envelope)
        self.assertEqual(captured.exception.code, "report_conflict")
        self.assertNotIn("secret-value", str(captured.exception))

    def test_malformed_202_responses_are_rejected(self):
        cases = [
            FakeResponse(body=b"{}"),
            FakeResponse(body=json.dumps(success_document()).encode() + b"{}"),
            FakeResponse(body=b"x" * ((1 << 20) + 1)),
            FakeResponse(body=b"{}", content_type="text/plain"),
            FakeResponse(body=b"{", content_type="application/json"),
            FakeResponse(
                body=json.dumps(
                    success_document(
                        [
                            {
                                "name": "unsafe",
                                "host": "https://user:password@example.invalid",
                                "interval": 60,
                                "type": "https",
                            }
                        ]
                    )
                ).encode()
            ),
            FakeResponse(
                body=json.dumps(
                    success_document(
                        [
                            {
                                "name": "unsafe",
                                "host": "https://example.invalid/?to%6ben=secret",
                                "interval": 60,
                                "type": "https",
                            }
                        ]
                    )
                ).encode()
            ),
            FakeResponse(
                body=json.dumps(
                    success_document(
                        [
                            {
                                "name": "unsafe",
                                "host": "https://example.invalid/%2e%2e/admin",
                                "interval": 60,
                                "type": "https",
                            }
                        ]
                    )
                ).encode()
            ),
            FakeResponse(
                body=json.dumps(
                    success_document(
                        [
                            {
                                "name": "unsafe",
                                "host": "example.invalid:443",
                                "interval": 60,
                                "type": "command",
                            }
                        ]
                    )
                ).encode()
            ),
        ]
        for response in cases:
            with self.subTest(body=response.body[:20]):
                with self.assertRaisesRegex(
                    DeviceTransportError,
                    "invalid_server_response",
                ):
                    self.client_for(FakeConnection(response)).send(self.envelope)

    def test_timeout_reset_truncation_and_dns_recovery(self):
        failures = [
            socket.timeout(),
            ConnectionResetError(),
            OSError("synthetic resolver failure"),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with self.assertRaises(DeviceTransportError) as captured:
                    self.client_for(
                        FakeConnection(connect_error=failure)
                    ).send(self.envelope)
                self.assertIn(
                    captured.exception.code,
                    {"transport_timeout", "transport_unavailable"},
                )

        truncated = FakeResponse(
            read_error=OSError("synthetic truncated response"),
        )
        with self.assertRaisesRegex(DeviceTransportError, "transport_unavailable"):
            self.client_for(FakeConnection(truncated)).send(self.envelope)

        connections = [
            FakeConnection(connect_error=OSError("DNS unavailable")),
            FakeConnection(success_response()),
        ]
        calls = []

        def factory(_config, _context):
            calls.append(len(calls))
            return connections[len(calls) - 1]

        client = DeviceHTTPSClient(self.config, connection_factory=factory)
        with self.assertRaisesRegex(DeviceTransportError, "transport_unavailable"):
            client.send(self.envelope)
        self.assertTrue(client.send(self.envelope)["accepted"])
        self.assertEqual(len(calls), 2)


class ResponseAndCacheTests(unittest.TestCase):
    def test_monitor_contract_and_transport_fields_are_fixed(self):
        valid = validate_success_response(
            success_document(
                [
                    {
                        "name": "https",
                        "host": "https://example.invalid/health",
                        "interval": 60,
                        "type": "https",
                    },
                    {
                        "name": "tcp",
                        "host": "example.invalid:443",
                        "interval": 30,
                        "type": "tcp",
                    },
                ]
            )
        )
        self.assertEqual(len(valid["monitors"]), 2)
        mutations = [
            {"server_url": "https://other.invalid"},
            {"device_id": "device-beta"},
            {"token_file": "/tmp/token"},
            {"verify_tls": False},
            {"command": "run"},
        ]
        for mutation in mutations:
            response = success_document()
            response.update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(
                ClientContractError
            ):
                validate_success_response(response)

    def test_monitor_cache_only_replaces_after_valid_response(self):
        cache = MonitorCache()
        valid = validate_success_response(
            success_document(
                [
                    {
                        "name": "safe",
                        "host": "https://example.invalid",
                        "interval": 60,
                        "type": "https",
                    }
                ]
            )
        )
        cache.update(valid)
        before = cache.snapshot()
        with self.assertRaises(ClientContractError):
            invalid = success_document(
                [
                    {
                        "name": "unsafe",
                        "host": "https://example.invalid/?token=secret",
                        "interval": 60,
                        "type": "https",
                    }
                ]
            )
            cache.update(validate_success_response(invalid))
        self.assertEqual(cache.snapshot(), before)

    def test_monitor_installation_has_no_command_channel(self):
        monitor_state = {}
        workers = []

        class Worker:
            daemon = False

            def __init__(self, **kwargs):
                workers.append(kwargs)

            def start(self):
                pass

        install_monitor_definitions(
            monitor_state,
            [
                {
                    "name": "safe",
                    "host": "https://example.invalid",
                    "interval": 60,
                    "type": "https",
                }
            ],
            thread_target=lambda **_kwargs: None,
            thread_factory=Worker,
        )
        self.assertEqual(
            set(monitor_state["safe"]),
            {"type", "host", "latency", "_interval", "_generation"},
        )
        self.assertEqual(len(workers), 1)
        install_monitor_definitions(
            monitor_state,
            [
                {
                    "name": "safe",
                    "host": "https://example.invalid",
                    "interval": 60,
                    "type": "https",
                }
            ],
            thread_target=lambda **_kwargs: None,
            thread_factory=Worker,
        )
        self.assertEqual(len(workers), 1)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.config = ClientV2Config(
            server_url="https://status.example.invalid",
            device_id="device-alpha",
            device_name=None,
            device_fqdn=None,
            token_file="/synthetic/not-read-by-stub",
            collection_interval_seconds=60,
        )

    def runner(self, outcomes, applied, logs, random_value=lambda: 1.0):
        class StubClient:
            def send(self, _envelope):
                outcome = outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        return DeviceV2Runner(
            config=self.config,
            collect_stats=lambda: valid_stats(),
            apply_monitors=lambda monitors: applied.append(monitors),
            client=StubClient(),
            cache=MonitorCache(),
            random_value=random_value,
            logger=logs.append,
            monotonic=lambda: 100.0,
        )

    def test_backoff_slow_paths_rate_limit_and_success_reset(self):
        applied = []
        logs = []
        outcomes = [
            DeviceTransportError("authorization_rejected"),
            DeviceTransportError("endpoint_unavailable"),
            DeviceTransportError("rate_limited", retry_after_seconds=45),
            success_document(),
        ]
        runner = self.runner(outcomes, applied, logs)
        self.assertEqual(runner.run_once(), 30.0)
        self.assertEqual(runner.run_once(), 30.0)
        self.assertEqual(runner.run_once(), 45.0)
        self.assertEqual(runner.run_once(), 60.0)
        self.assertEqual(runner.attempt, 0)
        self.assertEqual(applied, [[]])
        self.assertTrue(all(TOKEN not in entry for entry in logs))

    def test_authorization_failure_preserves_last_known_good_monitors(self):
        monitor = {
            "name": "safe",
            "host": "https://example.invalid",
            "interval": 60,
            "type": "https",
        }
        applied = []
        runner = self.runner(
            [
                success_document([monitor]),
                DeviceTransportError("authorization_rejected"),
            ],
            applied,
            [],
        )
        self.assertEqual(runner.run_once(), 60.0)
        before = runner.cache.snapshot()
        self.assertEqual(runner.run_once(), 30.0)
        self.assertEqual(runner.cache.snapshot(), before)
        self.assertEqual(applied, [[monitor]])

    def test_stale_and_conflict_reports_wait_for_normal_collection(self):
        logs = []
        runner = self.runner(
            [
                DeviceTransportError("stale_report"),
                DeviceTransportError("report_conflict"),
            ],
            [],
            logs,
            random_value=lambda: 0.0,
        )
        runner.attempt = 9
        self.assertEqual(runner.run_once(), 60.0)
        self.assertEqual(runner.attempt, 0)
        self.assertEqual(runner.run_once(), 60.0)
        self.assertEqual(runner.attempt, 0)
        self.assertEqual(logs, [
            "device_v2 transport: stale_report",
            "device_v2 transport: report_conflict",
        ])

    def test_full_jitter_cap_no_busy_loop_and_throttled_logs(self):
        outcomes = [DeviceTransportError("server_unavailable")] * 12
        logs = []
        runner = self.runner(outcomes, [], logs, random_value=lambda: 0.0)
        delays = [runner.run_once() for _ in range(12)]
        self.assertTrue(all(delay >= 1.0 for delay in delays))
        self.assertTrue(all(delay <= 300.0 for delay in delays))
        self.assertEqual(len(logs), 1)

    def test_interruptible_wait_does_not_sleep_in_test(self):
        applied = []
        logs = []
        runner = self.runner([success_document()], applied, logs)
        stop = threading.Event()

        original_apply = runner.apply_monitors

        def apply_and_stop(monitors):
            original_apply(monitors)
            stop.set()

        runner.apply_monitors = apply_and_stop
        runner.run_forever(stop)
        self.assertTrue(stop.is_set())
        self.assertEqual(applied, [[]])


if __name__ == "__main__":
    unittest.main()
