#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "hermes_config_summary.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_config_summary_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def write_config(directory, text):
    path = pathlib.Path(directory) / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def summary_for(text):
    with tempfile.TemporaryDirectory() as tmp:
        path = write_config(tmp, text)
        return MODULE.summarize_config(config_path=str(path), env={"HOME": tmp})


class ConfigSummaryTests(unittest.TestCase):
    def test_config_summary_rejects_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            real = root / "real"
            real.mkdir()
            config = write_config(real, "model:\n  provider: synthetic\n")
            linked = root / "linked"
            linked.symlink_to(real, target_is_directory=True)
            summary = MODULE.summarize_config(
                config_path=str(linked / config.name),
                env={"HOME": str(root)},
            )
            self.assertFalse(summary["config_found"])

    def test_release_b_allowlist_and_auxiliary_inheritance(self):
        data = summary_for("""
model:
  provider: openai-codex
  default: gpt-5.5
  base_url: https://user:pass@example.invalid/v1?api_key=hidden
  max_concurrency: 4
  timeout: 120
auxiliary:
  vision:
    provider: auto
    model: ""
    timeout: 120
  web_extract:
    provider: gemini
    model: gemini-3.1-flash-lite
    timeout: 360
    download_timeout: 30
  compression:
    provider: gemini
    model: ""
  session_search:
    provider: gemini
    model: not-allowlisted
delegation:
  provider: openai-codex
  model: gpt-5.5-mini
  reasoning_effort: medium
  max_concurrent_children: 3
  max_spawn_depth: 2
  child_timeout_seconds: 600
terminal:
  docker_volumes:
    - /srv/example/workspace:/workspace
    - /etc/localtime:/etc/localtime:ro
    - /srv/example/.env:/workspace/.env:ro
    - /srv/example/auth.json:/workspace/auth.json:ro
""")
        self.assertTrue(data["config_found"])
        self.assertEqual(data["main_model"], {
            "provider": "openai-codex",
            "model": "gpt-5.5",
            "base_url": "https://example.invalid/v1",
            "concurrency": 4,
            "timeout_seconds": 120.0,
        })
        by_name = {item["name"]: item for item in data["auxiliary_models"]}
        self.assertEqual(set(by_name), {"vision", "web_extract"})
        self.assertEqual(by_name["vision"]["source"], "main_model")
        self.assertEqual(by_name["vision"]["effective_model"], "gpt-5.5")
        self.assertEqual(by_name["web_extract"]["source"], "config")
        self.assertEqual(by_name["web_extract"]["effective_model"], "gemini-3.1-flash-lite")
        self.assertEqual(data["delegation"]["max_spawn_depth"], 2)
        self.assertEqual(data["docker_volumes"], [
            "/srv/example/workspace:/workspace",
            "/etc/localtime:/etc/localtime:ro",
        ])

    def test_all_supported_auxiliary_names_are_bounded(self):
        auxiliary = "\n".join(
            "  %s:\n    provider: auto\n    model: \"\"" % name
            for name in MODULE.AUXILIARY_KEYS
        )
        data = summary_for("model:\n  provider: example\n  model: main\nauxiliary:\n" + auxiliary)
        self.assertEqual([item["name"] for item in data["auxiliary_models"]], list(MODULE.AUXILIARY_KEYS))

    def test_sensitive_values_never_enter_summary(self):
        data = summary_for("""
model:
  provider: password=hidden-provider
  model: api_key=hidden-model
  api_key: model-secret-value
auxiliary:
  curator:
    provider: gemini
    model: gemini-safe
    token: auxiliary-secret-value
    extra_body:
      api_key: nested-secret-value
terminal:
  docker_volumes:
    - /srv/example/token-store:/tokens
""")
        serialized = json.dumps(data, sort_keys=True)
        for secret in ("hidden-provider", "hidden-model", "model-secret-value", "auxiliary-secret-value", "nested-secret-value", "token-store"):
            self.assertNotIn(secret, serialized)
        self.assertEqual(data["main_model"]["provider"], "[redacted]")
        self.assertTrue(data["auxiliary_models"][0]["credential_configured"])
        self.assertTrue(data["auxiliary_models"][0]["extra_body_configured"])

    def test_explicit_and_standard_profile_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            preferred = root / ".hermes" / "profiles" / "daily"
            legacy = root / "daily"
            preferred.mkdir(parents=True)
            legacy.mkdir()
            preferred_path = write_config(preferred, "model:\n  provider: preferred\n  model: current\n")
            write_config(legacy, "model:\n  provider: legacy\n  model: old\n")
            data = MODULE.summarize_config(profile="daily", hermes_root=tmp, profile_dir=str(legacy), env={"HOME": tmp})
            self.assertEqual(data["main_model"]["provider"], "preferred")
            explicit = MODULE.summarize_config(config_path=str(preferred_path), env={"HOME": tmp})
            self.assertEqual(explicit["main_model"]["model"], "current")
            self.assertNotIn("config_path", explicit)

    def test_missing_and_invalid_config_use_stable_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = MODULE.summarize_config(profile="missing", hermes_root=tmp, env={"HOME": tmp})
        self.assertEqual(missing, MODULE.empty_summary(False))
        invalid = summary_for("model: [unterminated")
        self.assertEqual(invalid, MODULE.empty_summary(True))

    def test_previous_snapshot_is_re_sanitized(self):
        data = MODULE.sanitize_summary_snapshot({
            "config_found": True,
            "main_model": {"provider": "password=hidden", "model": "safe", "base_url": "https://user:pass@example.invalid/v1?token=hidden"},
            "auxiliary_models": [{"name": "vision", "provider": "auto", "model": "", "effective_provider": "safe", "effective_model": "safe", "source": "main_model", "tools": ["ignored"]}],
            "delegation": {},
            "docker_volumes": ["/srv/example/.env:/workspace/.env", "/srv/example/workspace:/workspace"],
            "unexpected": "secret=hidden",
        })
        serialized = json.dumps(data, sort_keys=True)
        self.assertNotIn("hidden", serialized)
        self.assertNotIn("unexpected", serialized)
        self.assertEqual(data["docker_volumes"], ["/srv/example/workspace:/workspace"])


if __name__ == "__main__":
    unittest.main()
