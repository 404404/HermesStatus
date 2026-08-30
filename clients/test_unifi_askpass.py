import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class AskpassProgramTests(unittest.TestCase):
    def test_reads_credential_only_when_invoked_by_ssh(self):
        script = Path(__file__).with_name("unifi_askpass.py")
        with tempfile.NamedTemporaryFile(mode="w+") as handle:
            handle.write("prompt-secret\n")
            handle.flush()
            os.chmod(handle.name, 0o600)
            env = {"HERMESSTATUS_UNIFI_CREDENTIAL_FILE": handle.name}
            result = subprocess.run(
                [sys.executable, str(script), "Password:"],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "prompt-secret\n")
            self.assertEqual(result.stderr, "")

    def test_rejects_missing_or_world_readable_file(self):
        script = Path(__file__).with_name("unifi_askpass.py")
        env = {"HERMESSTATUS_UNIFI_CREDENTIAL_FILE": "/tmp/does-not-exist"}
        result = subprocess.run(
            [sys.executable, str(script), "Password:"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
