#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "check_release_boundaries.py"
SPEC = importlib.util.spec_from_file_location("check_release_boundaries", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReleaseBoundarySecretTests(unittest.TestCase):
    def test_detects_required_secret_families(self):
        cases = {
            "API key": "API_KEY=" + "live_" + "abcdefghijklmnopqrstuvwxyz",
            "Bearer token": "Authorization: " + "Bearer " + "abcdefghijklmnopqrstuvwxyz.123",
            "password": "password: " + "correct-horse-battery-staple",
            "Hermes token": "HERMES_TOKEN=" + "hermes_live_" + "abcdefghijklmnopqrstuvwxyz",
            "GitHub token": "GITHUB_TOKEN=" + "ghp_" + "abcdefghijklmnopqrstuvwxyz123456",
            "OpenAI-style key": "sk-" + "abcdefghijklmnopqrstuvwxyz123456",
            "private/SSH key": "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                self.assertIn(label, MODULE.secret_findings(content))

    def test_allows_explicit_examples_and_placeholders(self):
        content = """
API_KEY=example-api-key
Authorization: Bearer <token>
password=ci-placeholder
HERMES_TOKEN=${HERMES_TOKEN}
ADMIN_TOKEN=replace-me
"""
        self.assertEqual(MODULE.secret_findings(content), [])

    def test_parentheses_do_not_hide_a_secret(self):
        content = "API_KEY=" + "live_abc(def)"
        self.assertIn("API key", MODULE.secret_findings(content))

    def test_environment_file_policy(self):
        for name in (".env", "deploy/.env.production", "config/.env.local"):
            self.assertTrue(MODULE.forbidden_environment_file(name))
        for name in (".env.example", "config/.env.sample", "deploy/.env.template"):
            self.assertFalse(MODULE.forbidden_environment_file(name))


if __name__ == "__main__":
    unittest.main()
