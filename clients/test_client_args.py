import importlib.util
import runpy
import sys
import types
import unittest
from pathlib import Path


CLIENT_DIR = Path(__file__).resolve().parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))


class ClientArgumentTests(unittest.TestCase):
    def test_password_with_user_text_does_not_replace_username(self):
        if "psutil" not in sys.modules and importlib.util.find_spec("psutil") is None:
            sys.modules["psutil"] = types.ModuleType("psutil")

        arguments = [
            "SERVER=127.0.0.1",
            "PORT=35601",
            "USER=s01",
            "PASSWORD=USER_DEFAULT_PASSWORD",
            "INTERVAL=2",
            "NOTUSER=ignored",
        ]
        expected = {
            "SERVER": "127.0.0.1",
            "PORT": "35601",
            "USER": "s01",
            "PASSWORD": "USER_DEFAULT_PASSWORD",
            "INTERVAL": "2",
        }

        for filename in ("client-linux.py", "client-psutil.py"):
            with self.subTest(client=filename):
                namespace = runpy.run_path(str(CLIENT_DIR / filename))
                self.assertEqual(namespace["parse_cli_args"](arguments), expected)

    def test_both_clients_use_the_same_device_v2_protocol_owners(self):
        if "psutil" not in sys.modules and importlib.util.find_spec("psutil") is None:
            sys.modules["psutil"] = types.ModuleType("psutil")
        namespaces = [
            runpy.run_path(str(CLIENT_DIR / filename))
            for filename in ("client-linux.py", "client-psutil.py")
        ]
        for shared_name in (
            "load_client_selection",
            "create_device_v2_runner",
            "install_monitor_definitions",
        ):
            self.assertIs(
                namespaces[0][shared_name],
                namespaces[1][shared_name],
                f"{shared_name} was duplicated between Client entrypoints",
            )
        self.assertIsNot(
            namespaces[0]["_device_v2_stats_collector"],
            namespaces[1]["_device_v2_stats_collector"],
        )


if __name__ == "__main__":
    unittest.main()
