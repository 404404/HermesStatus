import importlib.util
import io
import json
import os
import pathlib
import stat
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock


SCRIPT = pathlib.Path(__file__).parents[1] / "migrate_stats_data.py"
SPEC = importlib.util.spec_from_file_location("migrate_stats_data", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StatsMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        self.source = self.root / "old" / "stats.json"
        self.source.parent.mkdir()
        self.document = {"servers": [], "sslcerts": [], "updated": "1"}
        self.source.write_text(json.dumps(self.document), encoding="utf-8")
        self.target = self.root / "new"

    def tearDown(self):
        self.temporary.cleanup()

    def test_dry_run_does_not_create_target(self):
        result = MODULE.migrate(self.source, self.target, False)
        self.assertEqual(result["mode"], "dry-run")
        self.assertFalse(self.target.exists())

    def test_apply_copies_atomically_with_private_mode(self):
        result = MODULE.migrate(self.source, self.target, True)
        destination = self.target / "stats.json"
        self.assertEqual(result["mode"], "apply")
        self.assertEqual(json.loads(destination.read_text()), self.document)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o644)
        self.assertEqual(list(self.target.glob(".stats-migration-*.tmp")), [])

    def test_nonempty_target_directory_is_rejected(self):
        self.target.mkdir()
        marker = self.target / "unrelated.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.MigrationError, "must be empty"):
            MODULE.migrate(self.source, self.target, False)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_existing_target_is_never_overwritten(self):
        self.target.mkdir()
        destination = self.target / "stats.json"
        destination.write_text("original", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.MigrationError, "refusing to overwrite"):
            MODULE.migrate(self.source, self.target, True)
        self.assertEqual(destination.read_text(encoding="utf-8"), "original")

    def test_source_symlink_is_rejected(self):
        link = self.root / "source-link.json"
        link.symlink_to(self.source)
        with self.assertRaisesRegex(MODULE.MigrationError, "symbolic link"):
            MODULE.migrate(link, self.target, False)

    def test_target_symlink_component_is_rejected(self):
        real = self.root / "real-target"
        real.mkdir()
        link = self.root / "target-link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(MODULE.MigrationError, "symbolic link"):
            MODULE.migrate(self.source, link / "child", False)

    def test_invalid_json_is_rejected(self):
        self.source.write_text("{invalid", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.MigrationError, "not valid JSON"):
            MODULE.migrate(self.source, self.target, False)

    def test_empty_source_is_rejected(self):
        self.source.write_bytes(b"")
        with self.assertRaisesRegex(MODULE.MigrationError, "not valid JSON"):
            MODULE.migrate(self.source, self.target, False)

    def test_secret_like_field_is_rejected(self):
        self.source.write_text(json.dumps({"servers": [], "api_key": "redacted"}))
        with self.assertRaisesRegex(MODULE.MigrationError, "secret-like field"):
            MODULE.migrate(self.source, self.target, False)

    def test_secret_rejection_output_does_not_echo_value_or_path(self):
        marker = "do-not-print-this-value"
        self.source.write_text(json.dumps({"servers": [], "password": marker}))
        stderr = io.StringIO()
        argv = [
            "migrate_stats_data.py",
            "--source",
            str(self.source),
            "--target-directory",
            str(self.target),
        ]
        with mock.patch("sys.argv", argv), redirect_stderr(stderr):
            self.assertEqual(MODULE.main(), 3)
        self.assertNotIn(marker, stderr.getvalue())
        self.assertNotIn(str(self.source), stderr.getvalue())

    def test_token_usage_counts_are_allowed(self):
        self.source.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "hermes": {
                                "profiles": [
                                    {
                                        "token_usage": {
                                            "input_tokens": 10,
                                            "output_tokens": 5,
                                            "total_tokens": 15,
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            )
        )
        result = MODULE.migrate(self.source, self.target, False)
        self.assertEqual(result["mode"], "dry-run")

    def test_source_change_during_copy_is_rejected(self):
        original = MODULE.verify_source_unchanged

        def mutate_then_verify(source, fingerprint, checksum):
            source.write_text(
                json.dumps({"servers": [{"name": "changed"}]}), encoding="utf-8"
            )
            return original(source, fingerprint, checksum)

        with mock.patch.object(
            MODULE, "verify_source_unchanged", side_effect=mutate_then_verify
        ):
            with self.assertRaisesRegex(MODULE.MigrationError, "changed"):
                MODULE.migrate(self.source, self.target, True)
        self.assertFalse((self.target / "stats.json").exists())
        self.assertEqual(list(self.target.glob(".stats-migration-*.tmp")), [])

    def test_interrupted_copy_removes_temporary_file(self):
        def interrupted(descriptor, data):
            os.write(descriptor, data[:4])
            os.close(descriptor)
            raise OSError("simulated interruption")

        with mock.patch.object(MODULE, "write_and_sync", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "simulated interruption"):
                MODULE.migrate(self.source, self.target, True)
        self.assertFalse((self.target / "stats.json").exists())
        self.assertEqual(list(self.target.glob(".stats-migration-*.tmp")), [])

    def test_temporary_checksum_mismatch_is_rejected(self):
        def corrupt(descriptor, data):
            with os.fdopen(descriptor, "wb") as output:
                output.write(b"{}")
                output.flush()
                os.fsync(output.fileno())

        with mock.patch.object(MODULE, "write_and_sync", side_effect=corrupt):
            with self.assertRaisesRegex(MODULE.MigrationError, "checksum mismatch"):
                MODULE.migrate(self.source, self.target, True)
        self.assertFalse((self.target / "stats.json").exists())

    def test_permission_error_has_sanitized_exit(self):
        stderr = io.StringIO()
        argv = [
            "migrate_stats_data.py",
            "--source",
            str(self.source),
            "--target-directory",
            str(self.target),
            "--apply",
        ]
        with mock.patch("sys.argv", argv), mock.patch.object(
            MODULE.tempfile, "mkstemp", side_effect=PermissionError("private path")
        ), redirect_stderr(stderr):
            self.assertEqual(MODULE.main(), 5)
        self.assertEqual(stderr.getvalue(), "stats migration failed: filesystem operation failed\n")
        self.assertNotIn(str(self.target), stderr.getvalue())

    def test_multi_node_and_dynamic_docker_counts_are_preserved(self):
        document = {
            "servers": [
                {"name": "offline", "docker": {"running": 0, "total": 0}},
                {
                    "name": "target",
                    "hardware": {"stale": False},
                    "docker": {"running": 5, "total": 8, "containers": []},
                    "hermes": {"profiles": [{"profile": "example"}]},
                },
            ]
        }
        self.source.write_text(json.dumps(document), encoding="utf-8")
        MODULE.migrate(self.source, self.target, True)
        copied = json.loads((self.target / "stats.json").read_text(encoding="utf-8"))
        self.assertEqual(copied, document)


if __name__ == "__main__":
    unittest.main()
