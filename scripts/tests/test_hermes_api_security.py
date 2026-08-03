#!/usr/bin/env python3
import importlib.util
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "scripts" / "export-hermes-status.py"


def load_exporter(config_path):
    old = os.environ.get("HERMES_EXPORT_CONFIG")
    os.environ["HERMES_EXPORT_CONFIG"] = str(config_path)
    try:
        spec = importlib.util.spec_from_file_location("export_hermes_api_test", EXPORTER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if old is None:
            os.environ.pop("HERMES_EXPORT_CONFIG", None)
        else:
            os.environ["HERMES_EXPORT_CONFIG"] = old


class FakeResponse(object):
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload

    def read(self, _limit):
        return self.payload


class FakeConnection(object):
    response = FakeResponse(200, b'{"status":"ok"}')
    request_headers = None
    raises = None

    def __init__(self, *_args, **_kwargs):
        pass

    def request(self, _method, _path, body=None, headers=None):
        type(self).request_headers = dict(headers or {})
        if type(self).raises:
            raise type(self).raises

    def getresponse(self):
        return type(self).response

    def close(self):
        pass


class HermesAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        profile_dir = root / "daily"
        profile_dir.mkdir()
        (profile_dir / ".env").write_text(
            "API_SERVER_ENABLED=true\nAPI_SERVER_HOST=0.0.0.0\nAPI_SERVER_PORT=18642\nAPI_SERVER_KEY=fixture-secret\n",
            encoding="utf-8",
        )
        config = root / "exporter.json"
        config.write_text(json.dumps({
            "hermes_root": str(root),
            "status_dir": str(root / "status"),
            "profiles": [{"name": "daily", "profile_dir": str(profile_dir)}],
        }), encoding="utf-8")
        self.module = load_exporter(config)

    def tearDown(self):
        self.temp.cleanup()

    def test_api_is_loopback_and_authorized_client_side_only(self):
        module = self.module
        self.assertEqual(module.api_base_url("daily"), "http://127.0.0.1:18642")
        old_connection = module.http.client.HTTPConnection
        try:
            FakeConnection.response = FakeResponse(200, b'{"status":"ok"}')
            FakeConnection.raises = None
            module.http.client.HTTPConnection = FakeConnection
            payload, error = module.http_json("daily", "/health")
        finally:
            module.http.client.HTTPConnection = old_connection
        self.assertEqual(payload, {"status": "ok"})
        self.assertIsNone(error)
        self.assertEqual(FakeConnection.request_headers["Authorization"], "Bearer fixture-secret")
        self.assertNotIn("fixture-secret", json.dumps(payload))

    def test_401_and_timeout_are_safe_structured_errors(self):
        module = self.module
        old_connection = module.http.client.HTTPConnection
        try:
            module.http.client.HTTPConnection = FakeConnection
            FakeConnection.raises = None
            FakeConnection.response = FakeResponse(401, b'{"detail":"Bearer fixture-secret"}')
            payload, error = module.http_json("daily", "/health")
            self.assertIsNone(payload)
            self.assertEqual(error["code"], "api_unauthorized")
            self.assertEqual(error["http_status"], 401)
            self.assertNotIn("fixture-secret", json.dumps(error))

            FakeConnection.raises = socket.timeout()
            payload, error = module.http_json("daily", "/health")
            self.assertIsNone(payload)
            self.assertEqual(error["code"], "api_timeout")
            self.assertTrue(error["retryable"])
        finally:
            FakeConnection.raises = None
            module.http.client.HTTPConnection = old_connection

    def test_api_jobs_sessions_pagination_usage_and_moa(self):
        module = self.module

        def fake_http(_profile, path, method="GET", payload=None):
            del method, payload
            responses = {
                "/health": {"status": "ok"},
                "/health/detailed": {"status": "ok", "active_sessions": 2},
                "/api/jobs": {"jobs": [
                    {"id": "a", "enabled": True, "usage": {"input_tokens": 5, "output_tokens": 1}},
                    {"id": "b", "enabled": False},
                    {"id": "c", "enabled": True, "paused": True},
                ]},
                "/api/sessions?limit=100&offset=0": {"has_more": True, "limit": 2, "offset": 0, "data": [
                    {"id": "s1", "status": "active", "usage": {"prompt_tokens": 10, "completion_tokens": 2}},
                    {"id": "s2", "status": "idle", "input_tokens": 7, "output_tokens": 3},
                ]},
                "/api/sessions?limit=100&offset=2": {"has_more": False, "limit": 2, "offset": 2, "data": [
                    {"id": "s3", "status": "running", "input_tokens": 1, "output_tokens": 1},
                ]},
                "/v1/toolsets": {"data": [{"name": "moa", "label": "Mixture of Agents", "description": "Consensus", "enabled": True, "configured": True, "tools": ["mixture_of_agents"]}]},
            }
            return (responses[path], None) if path in responses else (None, module.safe_error("unexpected", "Unexpected test path"))

        original = module.http_json
        try:
            module.http_json = fake_http
            api = module.collect_api("daily")
        finally:
            module.http_json = original
        self.assertEqual((api["jobs_active"], api["jobs_total"]), (1, 3))
        self.assertEqual((api["sessions_active"], api["sessions_total_count"]), (2, 3))
        self.assertFalse(api["sessions_has_more"])
        self.assertEqual(api["usage"], {
            "input_tokens": 23,
            "output_tokens": 7,
            "total_tokens": 30,
            "estimated": False,
            "source": "hermes_api_payload",
            "window_start": None,
            "window_end": None,
        })
        self.assertTrue(api["mixture_of_agents"]["available"])

    def test_collect_api_does_not_promote_nonhealthy_status_to_ok(self):
        module = self.module

        def collect_with_health(health):
            def fake_http(_profile, path, method="GET", payload=None):
                del method, payload
                responses = {
                    "/health": health,
                    "/health/detailed": {},
                    "/api/jobs": {"jobs": []},
                    "/api/sessions?limit=100&offset=0": {"data": []},
                    "/api/sessions": {"data": []},
                    "/v1/toolsets": {},
                }
                return (responses[path], None) if path in responses else (None, module.safe_error("unexpected", "Unexpected test path"))

            original = module.http_json
            try:
                module.http_json = fake_http
                return module.collect_api("daily")
            finally:
                module.http_json = original

        self.assertEqual(collect_with_health({"status": "degraded"})["status"], "unknown")
        self.assertEqual(collect_with_health({})["status"], "unknown")

    def test_cli_status_maps_model_provider_gateway_mode_and_counts(self):
        parsed = self.module.parse_cli_status("""
◆ Environment
  Model:        gpt-5.5
  Provider:     OpenAI Codex
◆ API Keys
  Google / Gemini  ✓ masked
◆ Auth Providers
  OpenAI Codex  ✓ logged in
    Refreshed:  2026-07-01 21:48:10 CST
◆ Gateway Service
  Status:       ✓ running
  Manager:      docker (foreground)
◆ Scheduled Jobs
  Jobs:         3 active, 4 total
◆ Sessions
  Active:       10 session(s)
""")
        self.assertEqual(parsed["model"], "gpt-5.5")
        self.assertEqual(parsed["provider"], "OpenAI Codex")
        self.assertEqual(parsed["usage_mode"], "auth_provider")
        self.assertEqual(parsed["gateway_service"], "running")
        self.assertEqual(parsed["manager_mode"], "docker (foreground)")
        self.assertEqual((parsed["scheduled_jobs_active"], parsed["scheduled_jobs_total"]), (3, 4))
        self.assertEqual(parsed["sessions_total"], 10)
        self.assertIsNotNone(self.module.normalize_timestamp(parsed["auth_refreshed_at"]))

    def test_cli_status_uses_explicit_opencode_api_mode_without_borrowing_refresh(self):
        parsed = self.module.parse_cli_status("""
◆ Environment
  Model:        deepseek-v4-pro
  Provider:     OpenCode Go
◆ API Keys
  Google / Gemini  ✓ masked
◆ Auth Providers
  OpenAI Codex  ✓ logged in
    Refreshed:  2026-07-01 21:48:10 CST
◆ API-Key Providers
  Kimi / Moonshot  ✓ configured
""")
        self.assertEqual(parsed["usage_mode"], "api")
        self.assertNotIn("auth_refreshed_at", parsed)

    def test_cli_status_matches_api_and_api_key_provider_names(self):
        google = self.module.parse_cli_status("""
◆ Environment
  Model:        gemini-2.5-flash
  Provider:     Google AI Studio
◆ API Keys
  Google / Gemini  ✓ masked
""")
        self.assertEqual(google["usage_mode"], "api")

        kimi = self.module.parse_cli_status("""
◆ Environment
  Model:        kimi-k2
  Provider:     Kimi
◆ API-Key Providers
  Kimi / Moonshot  ✓ configured
        """)
        self.assertEqual(kimi["usage_mode"], "api")

        opencode_zen = self.module.parse_cli_status("""
◆ Environment
  Model:        deepseek-v4-pro
  Provider:     OpenCode Zen
        """)
        self.assertEqual(opencode_zen["usage_mode"], "api")


if __name__ == "__main__":
    unittest.main()
