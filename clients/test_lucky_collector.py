import datetime
import json
import os
import ssl
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from lucky_collector import (
    LuckyAPIError,
    LuckyClient,
    LuckyCollector,
    MAX_RESPONSE_BYTES,
    _certificate_status,
    _parse_time,
    collector_from_environment,
    compare_versions,
    lucky_process_state,
    not_configured_lucky,
)


FIXED_NOW = datetime.datetime(2026, 7, 23, 2, 0, tzinfo=datetime.timezone.utc)
LUCKY_TIMEZONE = datetime.timezone(datetime.timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]


def normal_responses():
    return {
        "/version": {"ret": 0, "version": "2.27.2", "buildTime": "example build"},
        "/api/status": {"ret": 0, "data": {"PID": 4200, "Uptime": 86400}},
        "/api/ddnstasklist": {"ret": 0, "data": {"list": [{"Key": "one", "Remark": "Home IPv4", "Provider": "Example DNS", "Enable": True, "Status": "ok", "Type": "IPv4", "GetIpType": "network-interface", "RecordChanged": True, "UpdatedRecordCount": 2, "TotalRecordCount": 3, "LastSyncTime": "2026-07-23T01:58:00Z", "NextSyncTime": "2026-07-23T02:08:00Z", "Records": [{"UpdateStatus": "SYNC_SUCCESS"}, {"UpdateStatus": "SYNC_SUCCESS"}, {"UpdateStatus": "SYNC_LOC_RECORD_NOCHANGE"}]}]}},
        "/api/webservice/rules": {
            "ret": 0,
            "rulelist": [{
                "Key": "two",
                "RuleName": "Status Console",
                "Enable": True,
                "Status": "running",
                "Network": "https",
                "ListenPort": 443,
                "HTTPS": True,
                "SubRules": [
                    {"Enable": True},
                    {"Enable": True},
                    {"Enable": True},
                    {"Enable": False},
                ],
            }],
            "statistics": {"two": {"Connections": 6}},
        },
        "/api/portforwards": {"ret": 0, "data": {"list": [{"Key": "three", "Remark": "Secure Shell", "Enable": True, "Status": "running", "Protocol": "tcp", "Port": 22022, "TargetType": "tcp", "ConnectionCount": 2}]}},
        "/api/ssl": {"ret": 0, "data": {"list": [{"Key": "four", "Remark": "Primary certificate", "Enable": True, "Type": "acme", "CertsInfo": {"NotBeforeTime": "2026-06-01T00:00:00Z", "NotAfterTime": "2026-09-01T00:00:00Z", "Issuer": "Example Trust CA", "DNSNames": ["masked"]}}]}},
    }


class LuckyCollectorTests(unittest.TestCase):
    def test_disabled_is_stable_not_configured(self):
        self.assertEqual(LuckyCollector(enabled=False).collect(), not_configured_lucky())

    def test_disabled_ignores_invalid_optional_environment(self):
        environment = {
            "LUCKY_ENABLED": "false",
            "LUCKY_BASE_URL": "not a URL",
            "LUCKY_TIMEOUT_SECONDS": "invalid",
            "LUCKY_CERT_WARNING_DAYS": "invalid",
            "LUCKY_VERSION_CHECK_TTL": "invalid",
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            self.assertEqual(
                collector_from_environment().collect(),
                not_configured_lucky(),
            )

    def test_enabled_invalid_numbers_fall_back_to_safe_defaults(self):
        responses = normal_responses()
        environment = {
            "LUCKY_ENABLED": "true",
            "LUCKY_TIMEOUT_SECONDS": "invalid",
            "LUCKY_CERT_WARNING_DAYS": "invalid",
            "LUCKY_VERSION_CHECK_TTL": "invalid",
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            collector = collector_from_environment(
                request_func=lambda path, headers: responses[path]
            )
        payload = collector.collect(FIXED_NOW)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(collector.warning_days, 30)
        self.assertEqual(collector.version_check_ttl, 21600)
        self.assertEqual(collector.client.timeout, 5)

    def test_invalid_base_url_degrades_only_lucky(self):
        collector = LuckyCollector(enabled=True, base_url="https://example.invalid")
        payload = collector.collect(FIXED_NOW)
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["error"]["code"], "invalid_configuration")

    def test_normal_projection_contains_no_addresses_or_raw_data(self):
        responses = normal_responses()
        requests = []

        def request(path, headers):
            requests.append((path, headers))
            return responses[path]

        payload = LuckyCollector(enabled=True, request_func=request, local_timezone=LUCKY_TIMEZONE).collect(FIXED_NOW)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["version"]["current"], "2.27.2")
        self.assertIsNone(payload["version"]["latest"])
        self.assertIsNone(payload["version"]["update_available"])
        self.assertIsNone(payload["version"]["error"])
        self.assertEqual(payload["ip_resolution"]["resolved_ip_count"], 3)
        self.assertEqual(payload["dynamic_dns"]["total"], 1)
        self.assertEqual(payload["dynamic_dns"]["records"][0]["address_method"], "network-interface")
        self.assertEqual(payload["dynamic_dns"]["records"][0]["local_record_change_status"], "changed")
        self.assertEqual(payload["dynamic_dns"]["records"][0]["updated_records"], 2)
        self.assertEqual(payload["dynamic_dns"]["records"][0]["total_records"], 3)
        self.assertEqual(payload["dynamic_dns"]["records"][0]["last_update_at"], "2026-07-23T01:58:00Z")
        self.assertEqual(payload["dynamic_dns"]["records"][0]["next_sync_at"], "2026-07-23T02:08:00Z")
        self.assertEqual(payload["web_services"]["services"][0]["listen_port"], 443)
        self.assertEqual(payload["web_services"]["services"][0]["connection_count"], 6)
        self.assertEqual(payload["web_services"]["services"][0]["enabled_subrules"], 3)
        self.assertEqual(payload["web_services"]["services"][0]["total_subrules"], 4)
        self.assertEqual(payload["port_forwards"]["rules"][0]["protocol"], "tcp")
        self.assertEqual(payload["port_forwards"]["rules"][0]["connection_count"], 2)
        self.assertEqual(payload["certificates"]["items"][0]["status"], "valid")
        serialized = json.dumps(payload)
        self.assertNotIn("masked", serialized)
        self.assertNotIn("raw_response", serialized)
        self.assertTrue(all(path.startswith("/version") or path.startswith("/api/") for path, _ in requests))
        self.assertTrue(all("?" not in path for path, _ in requests))

    def test_real_lucky_ddns_and_forward_shapes_are_projected(self):
        responses = normal_responses()
        responses["/api/ddnstasklist"] = {
            "ret": 0,
            "data": [{
                "Key": "real-ddns",
                "TaskName": "IPv6 task",
                "TaskType": "IPv6",
                "Enable": True,
                "DNS": {"Name": "Example DNS", "Callback": "redacted"},
                "V4QueryIPType": "url",
                "V6QueryIPType": "netInterface",
                "LastSyncTime": "2026-07-23 20:20:38",
                "NextSyncTime": "2026-07-23 20:21:14",
                "Records": [
                    {"DomainName": "masked.example", "UpdateStatus": "SYNC_LOC_RECORD_NOCHANGE"},
                    {"DomainName": "masked.example", "UpdateStatus": "SYNC_LOC_RECORD_NOCHANGE"},
                ],
            }],
        }
        responses["/api/portforwards"] = {
            "ret": 0,
            "list": [{
                "Key": "real-forward",
                "Name": "IPv6 forward",
                "Enable": False,
                "ForwardTypes": ["tcp6", "udp6"],
                "ListenPorts": "26622",
                "TargetAddressList": ["masked"],
            }],
            "statistics": {
                "real-forward": {
                    "TCPCurrentConnections": 2,
                    "UDPCurrentConnections": 1,
                },
            },
        }

        payload = LuckyCollector(
            enabled=True,
            request_func=lambda path, headers: responses[path],
            local_timezone=LUCKY_TIMEZONE,
        ).collect(FIXED_NOW)
        record = payload["dynamic_dns"]["records"][0]
        self.assertEqual(record["provider"], "Example DNS")
        self.assertEqual(record["address_method"], "netInterface")
        self.assertEqual(record["local_record_change_status"], "unchanged")
        self.assertEqual(record["updated_records"], 0)
        self.assertEqual(record["total_records"], 2)
        self.assertEqual(record["record_type"], "IPv6")
        self.assertEqual(record["last_update_at"], "2026-07-23T12:20:38Z")
        self.assertEqual(record["next_sync_at"], "2026-07-23T12:21:14Z")
        self.assertEqual(payload["ip_resolution"]["resolved_ip_count"], 2)
        self.assertEqual(payload["ip_resolution"]["ipv6_count"], 2)
        forward = payload["port_forwards"]["rules"][0]
        self.assertEqual(forward["protocol"], "tcp6/udp6")
        self.assertEqual(forward["listen_port"], 26622)
        self.assertEqual(forward["connection_count"], 3)
        self.assertNotIn("masked.example", json.dumps(payload))

    def test_header_auth_uses_file_and_never_query(self):
        responses = normal_responses()
        seen_headers = []
        with tempfile.TemporaryDirectory() as root:
            token_file = Path(root) / "credential"
            token_file.write_text("fixture-value", encoding="utf-8")

            def request(path, headers):
                seen_headers.append(headers)
                return responses[path]

            LuckyCollector(
                enabled=True,
                auth_mode="open_token",
                token_file=str(token_file),
                request_func=request,
                local_timezone=LUCKY_TIMEZONE,
            ).collect(FIXED_NOW)
        self.assertTrue(all(headers.get("openToken") == "fixture-value" for headers in seen_headers))

    def test_auth_modes_keep_optional_tokens_and_send_no_header_when_disabled(self):
        responses = normal_responses()
        with tempfile.TemporaryDirectory() as root:
            token_file = Path(root) / "credential"
            token_file.write_text("fixture-value", encoding="utf-8")
            for auth_mode, expected_header in (
                ("open_token", "openToken"),
                ("admin_token", "Lucky-Admin-Token"),
                ("none", None),
            ):
                seen_headers = []
                client = LuckyClient(
                    "https://127.0.0.1:16601",
                    auth_mode=auth_mode,
                    token_file=str(token_file),
                    request_func=lambda path, headers: seen_headers.append(headers) or responses[path],
                )
                self.assertEqual(client.get("version")["version"], "2.27.2")
                token_headers = [name for name in ("openToken", "Lucky-Admin-Token") if name in seen_headers[0]]
                self.assertEqual(token_headers, [] if expected_header is None else [expected_header])

    def test_default_environment_uses_https_and_no_token_file(self):
        responses = normal_responses()
        headers_seen = []
        with mock.patch.dict(os.environ, {"LUCKY_ENABLED": "true"}, clear=True):
            collector = collector_from_environment(
                request_func=lambda path, headers: headers_seen.append(headers) or responses[path]
            )
        self.assertEqual(collector.client.base_url, "https://127.0.0.1:16601")
        self.assertEqual(collector.client.auth_mode, "none")
        self.assertIsNone(collector.client.token_file)
        collector.collect(FIXED_NOW)
        self.assertTrue(headers_seen)
        self.assertTrue(all("openToken" not in headers and "Lucky-Admin-Token" not in headers for headers in headers_seen))

    def test_loopback_url_policy_allows_http_and_https_but_rejects_remote(self):
        for url in ("http://127.0.0.1:16601", "https://127.0.0.1:16601", "https://[::1]:16601"):
            with self.subTest(url=url):
                LuckyClient(url)
        for url in ("https://example.invalid:16601", "https://192.168.88.11:16601"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    LuckyClient(url)

    def test_direct_json_and_ret_success_values_are_preserved(self):
        for ret in (0, "0", True):
            with self.subTest(ret=ret):
                payload = LuckyClient._unwrap({"ret": ret, "version": "2.27.2"})
                self.assertEqual(payload, {"ret": ret, "version": "2.27.2"})
        self.assertEqual(
            LuckyClient._unwrap({"ret": 0, "data": {"version": "2.27.2"}}),
            {"version": "2.27.2"},
        )

    def test_lucky_token_rejects_final_and_parent_symlinks(self):
        with tempfile.TemporaryDirectory() as root_value:
            root = Path(root_value)
            real = root / "real"
            real.mkdir()
            token = real / "credential"
            token.write_text("fixture-value", encoding="utf-8")
            final_link = root / "credential-link"
            final_link.symlink_to(token)
            parent_link = root / "linked"
            parent_link.symlink_to(real, target_is_directory=True)
            for path in (final_link, parent_link / "credential"):
                with self.subTest(path=path.name):
                    client = LuckyClient(
                        "http://127.0.0.1:16601",
                        token_file=str(path),
                    )
                    self.assertIsNone(client._token())

    def test_version_comparison_handles_prefix_and_prerelease(self):
        self.assertTrue(compare_versions("v2.27.2", "2.28.0"))
        self.assertTrue(compare_versions("2.28.0-rc.1", "2.28.0"))
        self.assertTrue(compare_versions("2.28.0-beta.2", "2.28.0-rc.1"))
        self.assertFalse(compare_versions("2.28.0", "2.28.0"))
        self.assertFalse(compare_versions("2.28.0+local.1", "2.28.0+remote.2"))
        self.assertIsNone(compare_versions("unknown", "2.28.0"))

    def test_missing_latest_version_is_not_reported_as_an_error(self):
        responses = normal_responses()
        calls = []

        def request(path, headers):
            calls.append(path)
            return responses[path]

        collector = LuckyCollector(enabled=True, request_func=request, local_timezone=LUCKY_TIMEZONE)
        version = collector.collect(FIXED_NOW)["version"]
        self.assertNotIn("/api/info", calls)
        self.assertIsNone(version["latest"])
        self.assertIsNone(version["checked_at"])
        self.assertFalse(version["stale"])
        self.assertIsNone(version["error"])

    def test_web_service_uses_rule_detail_and_statistics(self):
        responses = normal_responses()
        requests = []

        def request(path, headers):
            requests.append(path)
            return responses[path]

        payload = LuckyCollector(
            enabled=True,
            request_func=request,
            local_timezone=LUCKY_TIMEZONE,
        ).collect(FIXED_NOW)
        service = payload["web_services"]["services"][0]
        self.assertEqual(service["listen_port"], 443)
        self.assertEqual(service["connection_count"], 6)
        self.assertEqual(service["enabled_subrules"], 3)
        self.assertEqual(service["total_subrules"], 4)
        self.assertTrue(service["enabled"])
        self.assertIn("/api/webservice/rules", requests)
        self.assertNotIn("/api/webservice/rules_lite", requests)

    def test_web_service_falls_back_to_lite_when_primary_is_unavailable(self):
        responses = normal_responses()
        responses["/api/webservice/rules_lite"] = {
            "ret": 0,
            "list": [{"Key": "two", "Name": "Status Console"}],
        }
        responses["/api/webservice/rule/two"] = {
            "ret": 0,
            "rule": {
                "RuleKey": "two",
                "RuleName": "Status Console",
                "Network": "https",
                "ListenPort": 443,
                "HTTPS": True,
                "ProxyList": [{"Enable": True}],
            },
        }

        def request(path, headers):
            if path == "/api/webservice/rules":
                raise LuckyAPIError("not_found", 404)
            return responses[path]

        payload = LuckyCollector(
            enabled=True,
            request_func=request,
            local_timezone=LUCKY_TIMEZONE,
        ).collect(FIXED_NOW)
        self.assertEqual(payload["web_services"]["status"], "ok")
        self.assertEqual(payload["web_services"]["services"][0]["listen_port"], 443)

    def test_certificate_naive_time_uses_lucky_host_timezone(self):
        responses = normal_responses()
        responses["/api/ssl"]["data"]["list"][0]["CertsInfo"].update({
            "NotBeforeTime": "2026-06-25 00:00:00",
            "NotAfterTime": "2026-09-23 23:59:59",
        })
        payload = LuckyCollector(
            enabled=True,
            request_func=lambda path, headers: responses[path],
            local_timezone=LUCKY_TIMEZONE,
        ).collect(FIXED_NOW)
        certificate = payload["certificates"]["items"][0]
        self.assertEqual(certificate["not_before"], "2026-06-24T16:00:00Z")
        self.assertEqual(certificate["not_after"], "2026-09-23T15:59:59Z")

    def test_slash_timestamp_uses_configured_timezone_across_host_timezones(self):
        timestamp = "2026/07/23 20:20:38"
        self.assertEqual(
            _parse_time(timestamp, datetime.timezone.utc),
            "2026-07-23T20:20:38Z",
        )
        self.assertEqual(
            _parse_time(timestamp, LUCKY_TIMEZONE),
            "2026-07-23T12:20:38Z",
        )

    def test_certificate_status_boundaries(self):
        self.assertEqual(_certificate_status("2026-07-01T00:00:00Z", "2026-09-01T00:00:00Z", FIXED_NOW, 30)[0], "valid")
        self.assertEqual(_certificate_status("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", FIXED_NOW, 30)[0], "expiring")
        self.assertEqual(_certificate_status("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", FIXED_NOW, 30)[0], "expired")
        self.assertEqual(_certificate_status("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", FIXED_NOW, 30)[0], "not_yet_valid")
        self.assertEqual(_certificate_status(None, None, FIXED_NOW, 30)[0], "unknown")
        self.assertEqual(_certificate_status(None, None, FIXED_NOW, 30, True)[0], "invalid")

    def test_public_version_failure_degrades_only_lucky(self):
        def request(path, headers):
            raise LuckyAPIError("invalid_response", 502)

        payload = LuckyCollector(
            enabled=True,
            request_func=request,
            process_state_func=lambda: (True, 4242),
        ).collect(FIXED_NOW)
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["error"]["code"], "invalid_response")
        self.assertEqual(payload["error"]["http_status"], 502)
        self.assertTrue(payload["service"]["process_running"])
        self.assertEqual(payload["service"]["process_pid"], 4242)
        self.assertFalse(payload["service"]["api_reachable"])
        self.assertNotIn("status", payload["version"])
        self.assertNotIn("fixture-value", json.dumps(payload))

    def test_unavailable_lucky_reports_confirmed_stopped_process(self):
        payload = LuckyCollector(
            enabled=True,
            request_func=lambda path, headers: (_ for _ in ()).throw(LuckyAPIError("connection_refused")),
            process_state_func=lambda: (False, None),
        ).collect(FIXED_NOW)
        self.assertEqual(payload["status"], "unavailable")
        self.assertFalse(payload["service"]["process_running"])
        self.assertEqual(payload["service"]["state"], "stopped")

    def test_version_redirect_preserves_fixed_info_backend_failure(self):
        def request(path, headers):
            if path == "/version":
                raise LuckyAPIError("invalid_response", 307)
            self.assertEqual(path, "/api/info")
            raise LuckyAPIError("invalid_response", 502)

        payload = LuckyCollector(
            enabled=True,
            request_func=request,
            process_state_func=lambda: (True, 4242),
        ).collect(FIXED_NOW)
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["error"]["http_status"], 502)
        self.assertTrue(payload["service"]["process_running"])
        self.assertFalse(payload["service"]["api_reachable"])

    def test_process_state_reads_only_comm_and_never_process_arguments(self):
        with tempfile.TemporaryDirectory() as root:
            process = Path(root) / "4242"
            process.mkdir()
            (process / "comm").write_text("Lucky\n", encoding="utf-8")
            (process / "cmdline").write_text("--token=must-not-read", encoding="utf-8")
            self.assertEqual(lucky_process_state(root), (True, 4242))
        self.assertEqual(lucky_process_state("/does/not/exist"), (None, None))

    def test_process_state_accepts_only_proven_exact_names(self):
        for name, expected in (
            ("lucky", True),
            ("lucky_process", True),
            ("notlucky_process", False),
            ("lucky_process_old", False),
            ("my_lucky", False),
        ):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as root:
                    process = Path(root) / "4242"
                    process.mkdir()
                    (process / "comm").write_text(name + "\n", encoding="utf-8")
                    self.assertEqual(lucky_process_state(root), (expected, 4242 if expected else None))

    def test_https_verify_policy_is_explicit_without_fallback(self):
        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}

            def read(self, size):
                return b'{"version":"2.27.2"}'

            def __enter__(self):
                return self

            def __exit__(self, *unused):
                return False

        for verify_tls in (True, False):
            with self.subTest(verify_tls=verify_tls):
                opener = mock.Mock()
                opener.open.return_value = Response()
                with mock.patch("lucky_collector.urllib.request.build_opener", return_value=opener) as build_opener:
                    LuckyClient("https://127.0.0.1:16601", verify_tls=verify_tls).get("version")
                handlers = build_opener.call_args.args
                https_handlers = [handler for handler in handlers if isinstance(handler, urllib.request.HTTPSHandler)]
                if verify_tls:
                    self.assertEqual(https_handlers, [])
                else:
                    self.assertEqual(len(https_handlers), 1)
                    self.assertEqual(https_handlers[0]._context.verify_mode, ssl.CERT_NONE)

    def test_transport_response_failures_are_rejected(self):
        class Response:
            status = 200
            headers = {"Content-Type": "text/html"}

            def read(self, size):
                return b"<html>not json</html>"

            def __enter__(self):
                return self

            def __exit__(self, *unused):
                return False

        opener = mock.Mock()
        opener.open.return_value = Response()
        with mock.patch("lucky_collector.urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(LuckyAPIError, "invalid_response"):
                LuckyClient("https://127.0.0.1:16601").get("version")
        for failure, expected in (
            (urllib.error.HTTPError("https://127.0.0.1:16601/version", 302, "redirect", {}, None), "invalid_response"),
            (TimeoutError(), "timeout"),
            (OSError(), "connection_refused"),
        ):
            with self.subTest(expected=expected):
                opener = mock.Mock()
                opener.open.side_effect = failure
                with mock.patch("lucky_collector.urllib.request.build_opener", return_value=opener):
                    with self.assertRaisesRegex(LuckyAPIError, expected):
                        LuckyClient("https://127.0.0.1:16601").get("version")

        class TooLargeResponse(Response):
            headers = {"Content-Type": "application/json"}

            def read(self, size):
                return b"x" * (MAX_RESPONSE_BYTES + 1)

        opener = mock.Mock()
        opener.open.return_value = TooLargeResponse()
        with mock.patch("lucky_collector.urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(LuckyAPIError, "response_too_large"):
                LuckyClient("https://127.0.0.1:16601").get("version")

    def test_one_module_failure_is_isolated(self):
        responses = normal_responses()

        def request(path, headers):
            if path == "/api/ssl":
                raise LuckyAPIError("forbidden", 403)
            return responses[path]

        payload = LuckyCollector(enabled=True, request_func=request).collect(FIXED_NOW)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["certificates"]["error"]["code"], "forbidden")
        self.assertEqual(payload["dynamic_dns"]["status"], "ok")

    def test_fixture_matches_normal_contract_shape(self):
        payload = json.loads((ROOT / "testdata/lucky/normal.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["source"], "local_api")
        self.assertEqual(sum(payload["certificates"][name] for name in ("valid", "expiring", "expired", "not_yet_valid", "invalid", "unknown")), payload["certificates"]["total"])


if __name__ == "__main__":
    unittest.main()
