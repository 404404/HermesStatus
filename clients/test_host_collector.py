import datetime
import importlib.util
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from host_collector import (
    EXTENSION_VERSION,
    HostExtensionCollector,
    _docker_request,
    add_extension_payload,
    atomic_write_json,
    collect_cpu_model,
    collect_docker,
    collect_hardware,
    collect_host_os,
    collect_hwmon_temperatures,
    collect_smart,
    not_reported_docker,
    not_reported_hardware,
    not_reported_hermes,
    read_hermes_snapshot,
    smart_candidates,
)
from lucky_collector import not_configured_lucky


CLIENT_DIR = Path(__file__).resolve().parent
ROOT = CLIENT_DIR.parent
FIXTURES = CLIENT_DIR / "testdata"
FIXED_NOW = datetime.datetime(2026, 7, 15, 0, 0, tzinfo=datetime.timezone.utc)


def fixture_text(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name):
    return json.loads(fixture_text(name))


class SmartRunner(object):
    def __init__(self, json_output=None, text_output=None, unavailable=False):
        self.json_output = json_output
        self.text_output = text_output
        self.unavailable = unavailable
        self.commands = []

    def __call__(self, command, timeout):
        self.commands.append(list(command))
        if self.unavailable:
            raise FileNotFoundError("smartctl")
        if command[:2] == ["smartctl", "--scan"]:
            return 0, "/dev/example -d sat # fixture\n"
        if "-j" in command:
            return 0, self.json_output or ""
        return 0, self.text_output or ""


class HostCollectorTests(unittest.TestCase):
    def test_host_os_uses_mounted_pretty_name(self):
        name, error = collect_host_os(str(FIXTURES / "os-release"))
        self.assertEqual(name, "Example Linux 24.04 LTS")
        self.assertIsNone(error)

    def test_missing_host_os_does_not_fall_back_to_container(self):
        name, error = collect_host_os(str(FIXTURES / "missing-os-release"))
        self.assertEqual(name, "unknown")
        self.assertEqual(error["code"], "host_os_unavailable")

    def test_cpu_model_prefers_lscpu(self):
        output = json.dumps(
            {"lscpu": [{"field": "Model name:", "data": "Example CPU from lscpu"}]}
        )
        model, error = collect_cpu_model(lambda command, timeout: (0, output), str(FIXTURES / "cpuinfo"))
        self.assertEqual(model, "Example CPU from lscpu")
        self.assertIsNone(error)

    def test_cpu_model_falls_back_to_cpuinfo(self):
        model, error = collect_cpu_model(
            lambda command, timeout: (1, ""), str(FIXTURES / "cpuinfo")
        )
        self.assertEqual(model, "Example Processor 4125 @ 2.00GHz")
        self.assertIsNone(error)

    def test_hwmon_skips_damaged_sensor_and_selects_cpu(self):
        with tempfile.TemporaryDirectory() as root:
            chip = Path(root) / "hwmon0"
            chip.mkdir()
            (chip / "name").write_text("coretemp\n", encoding="utf-8")
            (chip / "temp1_label").write_text("Package id 0\n", encoding="utf-8")
            (chip / "temp1_input").write_text("42500\n", encoding="utf-8")
            (chip / "temp2_input").write_text("broken\n", encoding="utf-8")
            sensors = collect_hwmon_temperatures(root)
        self.assertEqual(len(sensors), 1)
        self.assertEqual(sensors[0]["value"], 42.5)
        self.assertEqual(sensors[0]["source"], "coretemp Package id 0")

    def test_hwmon_missing_returns_empty_list(self):
        self.assertEqual(collect_hwmon_temperatures("/does/not/exist"), [])

    def test_smart_json_uses_dynamic_logical_sector_size(self):
        runner = SmartRunner(json.dumps(fixture_json("smart-normal.json")))
        smart, error = collect_smart("/dev/example", runner)
        self.assertIsNone(error)
        self.assertEqual(smart["health"], "passed")
        self.assertEqual((smart["current"], smart["highest"], smart["lowest"]), (33, 48, 22))
        self.assertEqual(smart["hours"], 21399)
        self.assertEqual(smart["written_bytes"], 6302680682 * 4096)
        self.assertEqual(smart["read_bytes"], 3720709960 * 4096)
        self.assertIn(["smartctl", "-x", "/dev/example"], runner.commands)

    def test_smart_auto_scan_parses_device_and_type(self):
        runner = SmartRunner()
        self.assertEqual(smart_candidates("auto", runner)[0], ("/dev/example", "sat"))

    def test_smart_text_fallback(self):
        runner = SmartRunner("not-json", fixture_text("smart-normal.txt"))
        smart, error = collect_smart("/dev/example", runner)
        self.assertIsNone(error)
        self.assertEqual(smart["source"], "smartctl-text")
        self.assertEqual(smart["health"], "passed")
        self.assertEqual(smart["written_bytes"], 6302680682 * 512)
        self.assertEqual(smart["read_bytes"], 3720709960 * 512)

    def test_unknown_sector_size_never_assumes_512(self):
        data = fixture_json("smart-normal.json")
        del data["logical_block_size"]
        runner = SmartRunner(json.dumps(data), "=== START OF READ SMART DATA SECTION ===\n")
        smart, error = collect_smart("/dev/example", runner)
        self.assertEqual(error["code"], "sector_size_unknown")
        self.assertIsNone(smart["written_bytes"])
        self.assertIsNone(smart["read_bytes"])

    def test_smartctl_unavailable_is_safe_degraded_data(self):
        smart, error = collect_smart("/dev/example", SmartRunner(unavailable=True))
        self.assertIsNone(smart)
        self.assertEqual(error["code"], "smartctl_unavailable")
        self.assertNotIn("/dev/example", error["message"])

    def test_hardware_combines_hwmon_and_smart(self):
        with tempfile.TemporaryDirectory() as root:
            chip = Path(root) / "hwmon0"
            chip.mkdir()
            (chip / "name").write_text("coretemp\n", encoding="utf-8")
            (chip / "temp1_input").write_text("40000\n", encoding="utf-8")
            payload = collect_hardware(
                "Example CPU",
                [],
                root,
                "/dev/example",
                SmartRunner(json.dumps(fixture_json("smart-normal.json"))),
                FIXED_NOW,
            )
        self.assertEqual(payload["cpu_temperature"]["value"], 40.0)
        self.assertEqual(payload["disk_smart_status"], "passed")
        self.assertEqual(payload["updated_at"], "2026-07-15T00:00:00Z")
        self.assertFalse(payload["stale"])
        self.assertIsNone(payload["error"])

    def test_docker_normal_list_uses_release_c_allowlist(self):
        rows = fixture_json("docker-containers.json")
        payload = collect_docker(request_func=lambda path: rows, now=FIXED_NOW)
        self.assertEqual((payload["running"], payload["total"]), (1, 2))
        self.assertEqual(
            set(payload["containers"][0]),
            {"names", "image", "status", "ports"},
        )
        self.assertEqual(payload["updated_at"], "2026-07-15T00:00:00Z")

    def test_docker_empty_list(self):
        payload = collect_docker(request_func=lambda path: [], now=FIXED_NOW)
        self.assertEqual(payload["containers"], [])
        self.assertEqual(payload["total"], 0)
        self.assertFalse(payload["truncated"])

    def test_docker_unix_socket_uses_only_container_list_get(self):
        requests = []
        with tempfile.TemporaryDirectory() as root:
            socket_path = os.path.join(root, "docker.sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(socket_path)
            server.listen(1)

            def serve():
                connection, _ = server.accept()
                try:
                    requests.append(connection.recv(4096).decode("ascii"))
                    connection.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        b"Content-Length: 2\r\nConnection: close\r\n\r\n[]"
                    )
                finally:
                    connection.close()
                    server.close()

            thread = threading.Thread(target=serve)
            thread.start()
            response = _docker_request(socket_path, "/containers/json?all=1")
            thread.join(1)

        self.assertEqual(response, [])
        self.assertEqual(len(requests), 1)
        self.assertTrue(requests[0].startswith("GET /containers/json?all=1 HTTP/1.1\r\n"))
        self.assertNotIn("POST ", requests[0])

    def test_docker_socket_failure_is_degraded(self):
        def fail(_path):
            raise OSError("private socket path should not be returned")

        payload = collect_docker(request_func=fail)
        self.assertEqual(payload["containers"], [])
        self.assertTrue(payload["stale"])
        self.assertEqual(payload["error"]["code"], "docker_unavailable")
        self.assertNotIn("private socket", json.dumps(payload))

    def test_docker_limit_preserves_real_total(self):
        rows = fixture_json("docker-containers.json")
        payload = collect_docker(request_func=lambda path: rows, container_limit=1, now=FIXED_NOW)
        self.assertEqual(payload["total"], 2)
        self.assertEqual(len(payload["containers"]), 1)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["limit"], 1)

    def test_atomic_snapshot_replaces_complete_json(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "hardware.json")
            atomic_write_json(path, {"state": "first"})
            atomic_write_json(path, {"state": "second"})
            self.assertEqual(json.loads(Path(path).read_text(encoding="utf-8")), {"state": "second"})
            self.assertEqual([item.name for item in Path(root).iterdir()], ["hardware.json"])

    def test_hermes_snapshot_reader_accepts_only_profile_projection(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "hermes.json"
            path.write_text(json.dumps({
                "extension_version": EXTENSION_VERSION,
                "received_at": "2026-07-15T00:00:01Z",
                "profiles": [{"profile": "alpha", "api_status": "ok"}],
                "updated_at": "2026-07-15T00:00:00Z",
                "stale": False,
                "error": None,
                "unexpected": "not-forwarded",
            }), encoding="utf-8")
            payload = read_hermes_snapshot(str(path))
        self.assertEqual(payload["profiles"], [{"profile": "alpha", "api_status": "ok"}])
        self.assertEqual(payload["updated_at"], "2026-07-15T00:00:00Z")
        self.assertNotIn("extension_version", payload)
        self.assertNotIn("received_at", payload)
        self.assertNotIn("unexpected", payload)

    def test_hermes_snapshot_reader_degrades_missing_or_corrupt_data(self):
        missing = read_hermes_snapshot("/does/not/exist")
        self.assertEqual(missing["profiles"], [])
        self.assertTrue(missing["stale"])
        self.assertEqual(missing["error"]["code"], "snapshot_unavailable")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "hermes.json"
            path.write_text("{invalid", encoding="utf-8")
            corrupt = read_hermes_snapshot(str(path))
        self.assertEqual(corrupt["profiles"], [])
        self.assertEqual(corrupt["error"]["code"], "snapshot_unavailable")

    def test_collector_forwards_hermes_snapshot_without_source_access(self):
        with tempfile.TemporaryDirectory() as root:
            snapshot = Path(root) / "hermes.json"
            snapshot.write_text(json.dumps({
                "profiles": [{"profile": "alpha", "api_status": "ok"}],
                "updated_at": "2026-07-15T00:00:00Z",
                "stale": False,
                "error": None,
            }), encoding="utf-8")
            collector = HostExtensionCollector(
                host_os_release_file=str(FIXTURES / "os-release"),
                hermes_status_file=str(snapshot),
                status_dir="",
                command_runner=lambda command, timeout: (0, ""),
                docker_request=lambda path: [],
            )
            payload = collector.collect_hermes_once()
        self.assertEqual(payload["profiles"][0]["profile"], "alpha")
        self.assertEqual(collector.extension_payload()["hermes"], payload)

    def test_structured_payload_matches_schema_and_contains_no_legacy_or_secret(self):
        with tempfile.TemporaryDirectory() as root:
            chip = Path(root) / "hwmon0"
            chip.mkdir()
            (chip / "name").write_text("coretemp\n", encoding="utf-8")
            (chip / "temp1_input").write_text("40000\n", encoding="utf-8")
            hardware = collect_hardware(
                "Example CPU",
                [],
                root,
                "/dev/example",
                SmartRunner(json.dumps(fixture_json("smart-normal.json"))),
                FIXED_NOW,
            )
        docker_stats = collect_docker(
            request_func=lambda path: fixture_json("docker-containers.json"),
            now=FIXED_NOW,
        )
        payload = {
            "extension_version": EXTENSION_VERSION,
            "hardware": hardware,
            "docker": docker_stats,
            "hermes": not_reported_hermes(),
            "lucky": not_configured_lucky(),
        }
        self.assertFalse(any(key.endswith("_json") for key in payload))
        serialized = json.dumps(payload)
        self.assertNotIn('"command"', serialized)

        spec = importlib.util.spec_from_file_location(
            "contract_validator", ROOT / "scripts" / "validate_migration_contracts.py"
        )
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        schema_path = ROOT / "docs" / "migration" / "schema" / "agent-update-extension.schema.json"
        schema = validator.load_json(schema_path)
        validator.validate(payload, schema, schema_path)
        validator.validate_semantics(payload, CLIENT_DIR / "generated-payload.json")
        validator.scan_secrets(payload)

    def test_extension_failure_does_not_remove_native_update(self):
        class BrokenCollector(object):
            def extension_payload(self):
                raise RuntimeError("collector failed")

        update = {"cpu": 12.5, "memory_total": 1024}
        add_extension_payload(update, BrokenCollector())
        self.assertEqual(update["cpu"], 12.5)
        self.assertEqual(update["memory_total"], 1024)
        self.assertEqual(update["extension_version"], EXTENSION_VERSION)
        self.assertEqual(update["hardware"], not_reported_hardware())
        self.assertEqual(update["docker"], not_reported_docker())
        self.assertEqual(update["lucky"], not_configured_lucky())

    def test_collector_starts_with_stable_empty_hermes(self):
        collector = HostExtensionCollector(
            host_os_release_file=str(FIXTURES / "os-release"),
            smart_device="/dev/example",
            status_dir="",
            command_runner=lambda command, timeout: (
                (0, json.dumps({"lscpu": [{"field": "Model name:", "data": "Example CPU"}]}))
                if command == ["lscpu", "--json"]
                else (0, "")
            ),
            docker_request=lambda path: [],
        )
        payload = collector.extension_payload()
        self.assertEqual(payload["hermes"], not_reported_hermes())
        self.assertEqual(payload["hardware"], not_reported_hardware())
        self.assertEqual(payload["docker"], not_reported_docker())
        self.assertEqual(payload["lucky"], not_configured_lucky())

    def test_start_runs_collectors_immediately_and_payload_reads_are_cached(self):
        smart_json = json.dumps(fixture_json("smart-normal.json"))
        smart_text = fixture_text("smart-normal.txt")
        docker_calls = []

        def runner(command, timeout):
            if command == ["lscpu", "--json"]:
                return 0, json.dumps(
                    {"lscpu": [{"field": "Model name:", "data": "Example CPU"}]}
                )
            if "-j" in command:
                return 0, smart_json
            return 0, smart_text

        def docker_request(path):
            docker_calls.append(path)
            return []

        with tempfile.TemporaryDirectory() as root:
            chip = Path(root) / "hwmon0"
            chip.mkdir()
            (chip / "name").write_text("coretemp\n", encoding="utf-8")
            (chip / "temp1_input").write_text("40000\n", encoding="utf-8")
            collector = HostExtensionCollector(
                host_os_release_file=str(FIXTURES / "os-release"),
                hwmon_root=root,
                smart_device="/dev/example",
                hardware_interval=600,
                docker_interval=60,
                status_dir="",
                command_runner=runner,
                docker_request=docker_request,
            )
            collector.start()
            deadline = time.time() + 1
            payload = collector.extension_payload()
            while time.time() < deadline and (
                payload["hardware"]["updated_at"] is None
                or payload["docker"]["updated_at"] is None
            ):
                time.sleep(0.01)
                payload = collector.extension_payload()
            for _ in range(10):
                collector.extension_payload()
            collector.stop()

        self.assertIsNotNone(payload["hardware"]["updated_at"])
        self.assertIsNotNone(payload["docker"]["updated_at"])
        self.assertEqual(docker_calls, ["/containers/json?all=1"])


if __name__ == "__main__":
    unittest.main()
