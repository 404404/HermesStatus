#!/usr/bin/env python3
import datetime as dt
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "scripts" / "export-hermes-status.py"


def load_exporter(config_path):
    old = os.environ.get("HERMES_EXPORT_CONFIG")
    os.environ["HERMES_EXPORT_CONFIG"] = str(config_path)
    try:
        spec = importlib.util.spec_from_file_location("export_hermes_registry_test", EXPORTER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if old is None:
            os.environ.pop("HERMES_EXPORT_CONFIG", None)
        else:
            os.environ["HERMES_EXPORT_CONFIG"] = old


def profile_payload(module, name):
    now = module.utc_timestamp()
    return {
        "profile": name,
        "agent_version": "0.3.0",
        "api_status": "ok",
        "service_status": "ok",
        "gateway_service": "running",
        "manager_mode": "docker (foreground)",
        "usage_mode": "api",
        "provider": "Example Provider",
        "model": "example-model",
        "auth_refreshed_at": None,
        "scheduled_jobs_active": 1,
        "scheduled_jobs_total": 1,
        "sessions_active": 1,
        "sessions_total": 2,
        "sessions_has_more": False,
        "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "estimated": False, "source": "hermes_api_payload", "window_start": None, "window_end": None},
        "config_summary": module.sanitize_summary_snapshot({"config_found": False, "docker_volumes": []}),
        "mixture_of_agents": module.sanitize_mixture_of_agents({}),
        "updated_at": now,
        "received_at": now,
        "stale": False,
        "error": None,
    }


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.status = self.root / "status"
        self.config = self.root / "exporter.json"

    def tearDown(self):
        self.temp.cleanup()

    def write_registry(self, names):
        for name in names:
            (self.root / name).mkdir(exist_ok=True)
        self.config.write_text(json.dumps({
            "hermes_root": str(self.root),
            "status_dir": str(self.status),
            "profiles": [{"name": name, "profile_dir": str(self.root / name), "api": {"enabled": True, "port": 18000 + index}} for index, name in enumerate(names)],
        }), encoding="utf-8")

    def test_three_profiles_and_dynamic_add_delete_rename(self):
        self.write_registry(["alpha", "beta", "gamma"])
        module = load_exporter(self.config)
        original = module.profile_stats
        try:
            module.profile_stats = lambda name, _directory, _previous=None: profile_payload(module, name)
            root = module.main()
            self.assertEqual([item["profile"] for item in root["profiles"]], ["alpha", "beta", "gamma"])
            self.assertEqual(sorted(path.name for path in self.status.glob("*.json")), ["alpha.json", "beta.json", "gamma.json", "hermes.json"])

            self.write_registry(["alpha", "delta", "epsilon"])
            root = module.main()
            self.assertEqual([item["profile"] for item in root["profiles"]], ["alpha", "delta", "epsilon"])
            self.assertEqual(sorted(path.name for path in self.status.glob("*.json")), ["alpha.json", "delta.json", "epsilon.json", "hermes.json"])
            self.assertFalse(any(path.suffix == ".tmp" for path in self.status.iterdir()))
            decoded = json.loads((self.status / "hermes.json").read_text(encoding="utf-8"))
            self.assertEqual([item["profile"] for item in decoded["profiles"]], ["alpha", "delta", "epsilon"])
        finally:
            module.profile_stats = original

    def test_duplicate_and_invalid_registry_names_are_ignored(self):
        self.config.write_text(json.dumps({
            "hermes_root": str(self.root),
            "status_dir": str(self.status),
            "profiles": ["daily", "daily", "bad/name", "renamed.profile"],
        }), encoding="utf-8")
        module = load_exporter(self.config)
        self.assertEqual(module.PROFILES, ["daily", "renamed.profile"])

    def test_api_cli_snapshot_fallback_order(self):
        self.write_registry(["daily"])
        module = load_exporter(self.config)
        profile_dir = self.root / "daily"
        previous = profile_payload(module, "daily")
        previous["model"] = "snapshot-model"
        previous["updated_at"] = "2026-07-14T00:00:00Z"

        originals = (module.service_status, module.hermes_cli_status, module.collect_api, module.hermes_agent_version, module.summarize_config, module.collect_local_usage)
        try:
            module.service_status = lambda _profile: ("unknown", "")
            module.hermes_agent_version = lambda: "0.3.0"
            module.summarize_config = lambda **_kwargs: module.sanitize_summary_snapshot({"config_found": False, "docker_volumes": []})
            module.collect_local_usage = lambda _path: module.unavailable_usage()
            module.collect_api = lambda _profile: {
                "status": "unknown",
                "errors": [module.safe_error("api_unauthorized", "Hermes API authorization failed", "hermes-api", False, 401)],
                "usage": module.unavailable_usage(),
                "mixture_of_agents": module.sanitize_mixture_of_agents({"error": "api_unauthorized"}),
            }
            module.hermes_cli_status = lambda _profile: """
◆ Environment
  Model: cli-model
  Provider: CLI Provider
◆ Gateway Service
  Status: running
  Manager: docker (foreground)
◆ Scheduled Jobs
  Jobs: 2 active, 3 total
◆ Sessions
  Active: 4 session(s)
"""
            cli_payload = module.profile_stats("daily", profile_dir, previous)
            self.assertEqual(cli_payload["model"], "cli-model")
            self.assertFalse(cli_payload["stale"])
            self.assertEqual(cli_payload["api_status"], "unauthorized")
            self.assertEqual((cli_payload["scheduled_jobs_active"], cli_payload["scheduled_jobs_total"]), (2, 3))

            module.hermes_cli_status = lambda _profile: ""
            snapshot_payload = module.profile_stats("daily", profile_dir, previous)
            self.assertEqual(snapshot_payload["model"], "snapshot-model")
            self.assertEqual(snapshot_payload["updated_at"], "2026-07-14T00:00:00Z")
            self.assertTrue(snapshot_payload["stale"])
        finally:
            (module.service_status, module.hermes_cli_status, module.collect_api, module.hermes_agent_version, module.summarize_config, module.collect_local_usage) = originals

    def test_local_usage_preserves_recursive_1_0_window(self):
        self.write_registry(["daily"])
        module = load_exporter(self.config)
        logs = self.root / "daily" / "logs"
        logs.mkdir()
        now = dt.datetime(2026, 7, 16, 12, 0, tzinfo=dt.timezone.utc)
        (logs / "run.json").write_text(json.dumps({
            "timestamp": "2026-07-15T08:00:00Z",
            "result": {"usage": {"prompt_tokens": 13, "completion_tokens": 5}},
        }), encoding="utf-8")
        usage = module.collect_local_usage(self.root / "daily", now=now)
        self.assertEqual((usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]), (13, 5, 18))
        self.assertTrue(usage["estimated"])
        self.assertEqual(usage["source"], "local_logs")
        self.assertIsNotNone(usage["window_start"])
        self.assertIsNotNone(usage["window_end"])


if __name__ == "__main__":
    unittest.main()
