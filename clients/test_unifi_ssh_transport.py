import os
import stat
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from unifi_ssh_transport import TransportError, _run_fixed, _validate_file


class UniFiSSHTransportTests(unittest.TestCase):
    def _config(self, known_hosts):
        return SimpleNamespace(
            known_hosts_file=str(known_hosts),
            credential_file=str(known_hosts),
            connect_timeout_seconds=3,
            port=22,
            username="root",
            host="192.168.68.1",
        )

    def test_missing_known_hosts_is_configuration_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "missing")
            with self.assertRaises(TransportError) as captured:
                _run_fixed("printf fixed", self._config(path))
            self.assertEqual(str(captured.exception), "host_key_configuration")

    def test_root_accepts_strictly_private_host_file_owned_by_host_user(self):
        with tempfile.NamedTemporaryFile() as handle:
            os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
            with patch("unifi_ssh_transport.os.geteuid", return_value=0):
                _validate_file(handle.name, "known_hosts_file", allow_root_readable=True)

    def test_host_key_mismatch_is_not_authentication_failure(self):
        with tempfile.NamedTemporaryFile() as handle:
            os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
            result = SimpleNamespace(returncode=255, stderr="Host key verification failed.", stdout="")
            with patch("unifi_ssh_transport.subprocess.run", return_value=result), patch(
                "unifi_ssh_transport._askpass", return_value=handle.name
            ):
                with self.assertRaises(TransportError) as captured:
                    _run_fixed("printf fixed", self._config(handle.name))
            self.assertEqual(str(captured.exception), "host_key_failure")

    def test_auth_rejection_before_challenge_is_distinct(self):
        with tempfile.NamedTemporaryFile() as handle:
            os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
            result = SimpleNamespace(returncode=255, stderr="Next authentication method: keyboard-interactive\nuserauth_kbdint: disable: no info_req_seen", stdout="")
            with patch("unifi_ssh_transport.subprocess.run", return_value=result):
                with self.assertRaises(TransportError) as captured:
                    _run_fixed("printf fixed", self._config(handle.name))
            self.assertEqual(str(captured.exception), "ssh_auth_failure")

    def test_keyboard_interactive_policy_disables_publickey_and_password(self):
        with tempfile.NamedTemporaryFile(mode="w+") as handle:
            handle.write("not-a-real-secret\n")
            handle.flush()
            os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
            result = SimpleNamespace(returncode=0, stderr="", stdout="fixed\n")
            with patch("unifi_ssh_transport.subprocess.run", return_value=result) as run:
                output = _run_fixed("printf fixed", self._config(handle.name))
            self.assertEqual(output, "fixed\n")
            command = run.call_args.args[0]
            self.assertIn("-o", command)
            self.assertIn("PubkeyAuthentication=no", command)
            self.assertIn("PasswordAuthentication=no", command)
            self.assertIn("KbdInteractiveAuthentication=yes", command)
            self.assertIn("PreferredAuthentications=keyboard-interactive", command)
            environment = run.call_args.kwargs["env"]
            self.assertNotIn("not-a-real-secret", " ".join(command))
            self.assertNotIn("not-a-real-secret", " ".join(str(value) for value in environment.values()))

    def test_askpass_reads_password_only_at_prompt_time(self):
        with tempfile.NamedTemporaryFile(mode="w+") as handle:
            handle.write("prompt-secret\n")
            handle.flush()
            os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
            askpass = __import__("unifi_ssh_transport")._askpass(handle.name)
            try:
                self.assertEqual(os.stat(askpass).st_mode & 0o777, 0o700)
                import subprocess
                self.assertEqual(subprocess.check_output([askpass], text=True), "prompt-secret\n")
                with open(askpass, encoding="utf-8") as script:
                    self.assertNotIn("prompt-secret", script.read())
            finally:
                try:
                    os.unlink(askpass)
                except OSError:
                    pass

    def test_auth_rejection_is_distinct(self):
        with tempfile.NamedTemporaryFile() as handle:
            os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
            result = SimpleNamespace(returncode=255, stderr="Permission denied (keyboard-interactive).", stdout="")
            with patch("unifi_ssh_transport.subprocess.run", return_value=result), patch(
                "unifi_ssh_transport._askpass", return_value=handle.name
            ):
                with self.assertRaises(TransportError) as captured:
                    _run_fixed("printf fixed", self._config(handle.name))
            self.assertEqual(str(captured.exception), "ssh_auth_failure")


if __name__ == "__main__":
    unittest.main()
