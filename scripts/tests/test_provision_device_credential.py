import base64
import hashlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "provision_device_credential.py"
SPEC = importlib.util.spec_from_file_location(
    "provision_device_credential",
    SCRIPT_PATH,
)
provisioner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = provisioner
SPEC.loader.exec_module(provisioner)


NOT_BEFORE = "2026-07-29T00:00:00Z"
NOT_AFTER = "2027-07-29T00:00:00Z"


class ProvisionDeviceCredentialTests(unittest.TestCase):
    def arguments(self, root, **overrides):
        values = {
            "device_id": "device-alpha",
            "client_token_file": str(root / "client.token"),
            "server_credential_file": str(root / "device-alpha.json"),
            "slot": "current",
            "not_before": NOT_BEFORE,
            "not_after": NOT_AFTER,
            "overwrite": False,
            "dry_run": False,
        }
        values.update(overrides)
        return provisioner.ProvisionArguments(**values)

    def test_creates_private_atomic_token_and_digest_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout = io.StringIO()
            random_bytes = bytes(range(32))
            provisioner.provision(
                self.arguments(root),
                stdout=stdout,
                token_factory=lambda count: random_bytes,
            )
            token_path = root / "client.token"
            credential_path = root / "device-alpha.json"
            token = token_path.read_text(encoding="ascii").rstrip("\n")
            expected = base64.urlsafe_b64encode(random_bytes).rstrip(b"=").decode()
            self.assertEqual(token, expected)
            self.assertEqual(len(token), 43)
            self.assertRegex(token, r"^[A-Za-z0-9_-]{43}$")
            record = json.loads(credential_path.read_text(encoding="utf-8"))
            self.assertEqual(record["device_id"], "device-alpha")
            self.assertEqual(record["credentials"][0]["id"], "current")
            self.assertEqual(
                record["credentials"][0]["digest"],
                hashlib.sha256(token.encode("ascii")).hexdigest(),
            )
            self.assertNotIn(token, credential_path.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(token_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(credential_path.stat().st_mode), 0o600)
            self.assertNotIn(token, stdout.getvalue())
            self.assertIn("device_id: device-alpha", stdout.getvalue())
            self.assertEqual(
                [path for path in root.iterdir() if path.name.startswith(".hermesstatus-")],
                [],
            )

    def test_dry_run_validates_without_randomness_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout = io.StringIO()

            def forbidden_random(_count):
                raise AssertionError("dry-run generated a token")

            provisioner.provision(
                self.arguments(root, dry_run=True),
                stdout=stdout,
                token_factory=forbidden_random,
            )
            self.assertEqual(list(root.iterdir()), [])
            self.assertEqual(
                stdout.getvalue(),
                "validation success\ndevice_id: device-alpha\n",
            )

    def test_invalid_existing_symlink_directory_and_same_targets_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = []
            cases.append(self.arguments(root, device_id="INVALID"))

            existing = root / "existing.token"
            existing.write_text("existing", encoding="ascii")
            cases.append(self.arguments(root, client_token_file=str(existing)))

            target = root / "target"
            target.write_text("target", encoding="ascii")
            symlink = root / "symlink"
            symlink.symlink_to(target)
            cases.append(self.arguments(root, client_token_file=str(symlink), overwrite=True))

            target_directory = root / "directory"
            target_directory.mkdir()
            cases.append(
                self.arguments(
                    root,
                    client_token_file=str(target_directory),
                    overwrite=True,
                )
            )
            same = root / "same"
            cases.append(
                self.arguments(
                    root,
                    client_token_file=str(same),
                    server_credential_file=str(same),
                )
            )

            for arguments in cases:
                with self.subTest(arguments=arguments):
                    with self.assertRaises(provisioner.ProvisionError):
                        provisioner.provision(arguments, stdout=io.StringIO())

    def test_next_rotation_preserves_current_and_overwrites_only_regular_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server_path = root / "device-alpha.json"
            current_digest = "a" * 64
            server_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "device_id": "device-alpha",
                        "algorithm": "sha256",
                        "credentials": [
                            {
                                "id": "current",
                                "digest": current_digest,
                                "not_before": NOT_BEFORE,
                                "not_after": NOT_AFTER,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            os.chmod(server_path, 0o600)
            next_bytes = b"N" * 32
            provisioner.provision(
                self.arguments(
                    root,
                    client_token_file=str(root / "next.token"),
                    slot="next",
                    overwrite=True,
                ),
                stdout=io.StringIO(),
                token_factory=lambda count: next_bytes,
            )
            record = json.loads(server_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [credential["id"] for credential in record["credentials"]],
                ["current", "next"],
            )
            self.assertEqual(record["credentials"][0]["digest"], current_digest)
            next_token = (root / "next.token").read_text(encoding="ascii").strip()
            self.assertEqual(
                record["credentials"][1]["digest"],
                hashlib.sha256(next_token.encode("ascii")).hexdigest(),
            )
            self.assertEqual(stat.S_IMODE(server_path.stat().st_mode), 0o600)

    def test_source_has_no_network_or_service_mutation_capability(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "import socket",
            "import urllib",
            "import requests",
            "subprocess",
            "docker compose",
            "systemctl",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("print(token", source)

    def test_unwritable_parent_is_rejected_when_effective_user_is_not_root(self):
        if os.geteuid() == 0:
            self.skipTest("root bypasses directory permission checks")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.chmod(root, 0o500)
            try:
                with self.assertRaises(provisioner.ProvisionError) as caught:
                    provisioner.provision(
                        self.arguments(root),
                        stdout=io.StringIO(),
                    )
                self.assertEqual(caught.exception.code, "target_not_writable")
            finally:
                os.chmod(root, 0o700)


if __name__ == "__main__":
    unittest.main()
