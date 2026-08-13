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
    build_block_device_graph,
    collect_client_build,
    collect_cpu_details,
    collect_cpu_model,
    collect_cpu_usage,
    collect_docker,
    collect_filesystems,
    collect_hardware,
    collect_host_os,
    collect_hwmon_temperatures,
    collect_memory_details,
    collect_smart,
    collect_smart_devices,
    not_reported_docker,
    not_reported_hardware,
    not_reported_hermes,
    read_hermes_snapshot,
    resolve_backing_physical_disks,
    smart_candidates,
)
from lucky_collector import not_configured_lucky
from easytier_collector import not_configured_easytier


CLIENT_DIR = Path(__file__).resolve().parent
ROOT = CLIENT_DIR.parent
FIXTURES = CLIENT_DIR / "testdata"
FIXED_NOW = datetime.datetime(2026, 7, 15, 0, 0, tzinfo=datetime.timezone.utc)


def fixture_text(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name):
    return json.loads(fixture_text(name))


def set_smart_temperature(payload, value):
    for page in payload.get("ata_device_statistics", {}).get("pages", []):
        if page.get("number") != 5:
            continue
        for item in page.get("table", []):
            if item.get("offset") == 8:
                item["value"] = value
                return
    raise AssertionError("fixture has no current temperature")


class SmartRunner(object):
    def __init__(
        self,
        json_output=None,
        text_output=None,
        unavailable=False,
        json_returncode=0,
        text_returncode=0,
    ):
        self.json_output = json_output
        self.text_output = text_output
        self.unavailable = unavailable
        self.json_returncode = json_returncode
        self.text_returncode = text_returncode
        self.commands = []

    def __call__(self, command, timeout):
        self.commands.append(list(command))
        if self.unavailable:
            raise FileNotFoundError("smartctl")
        if command[:2] == ["smartctl", "--scan"]:
            return 0, "/dev/example -d sat # fixture\n"
        if "-j" in command:
            return self.json_returncode, self.json_output or ""
        return self.text_returncode, self.text_output or ""


class MultiSmartRunner(object):
    def __init__(self, payloads, unavailable=()):
        self.payloads = dict(payloads)
        self.unavailable = set(unavailable)
        self.commands = []

    def __call__(self, command, timeout):
        self.commands.append(list(command))
        if command[:2] == ["smartctl", "--scan"]:
            return 0, ""
        if command[:1] == ["lsblk"]:
            return 0, json.dumps(
                {
                    "blockdevices": [
                        {"name": "sda", "kname": "sda", "type": "disk", "size": 1000},
                        {"name": "sdb", "kname": "sdb", "type": "disk", "size": 2000},
                    ]
                }
            )
        candidate = command[-1]
        if candidate in self.unavailable:
            raise OSError("synthetic unavailable")
        payload = self.payloads[candidate]
        return 0, payload if "-j" in command else "SMART overall-health self-assessment test result: PASSED\n"


class HostCollectorTests(unittest.TestCase):
    def test_easytier_uses_resolved_collector_interval(self):
        class EasyTierFixture(object):
            config = {"interval_seconds": 75}

            def collect(self):
                return {}

        collector = HostExtensionCollector(
            host_os_release_file=str(FIXTURES / "os-release"),
            status_dir="",
            command_runner=lambda command, timeout: (0, ""),
            docker_request=lambda path: [],
            easytier_collector=EasyTierFixture(),
        )
        self.assertEqual(collector.easytier_interval, 75)

    def test_host_os_uses_mounted_pretty_name(self):
        name, error = collect_host_os(str(FIXTURES / "os-release"))
        self.assertEqual(name, "Example Linux 24.04 LTS")
        self.assertIsNone(error)

    def test_missing_host_os_does_not_fall_back_to_container(self):
        name, error = collect_host_os(str(FIXTURES / "missing-os-release"))
        self.assertEqual(name, "unknown")
        self.assertEqual(error["code"], "host_os_unavailable")

    def test_dsm_identity_does_not_degrade_hardware_when_os_release_is_absent(self):
        with tempfile.TemporaryDirectory() as root:
            version = Path(root) / "VERSION"
            version.write_text(
                "productversion=7.2.1\nbuildnumber=69057\nsmallfixnumber=1\n",
                encoding="utf-8",
            )
            collector = HostExtensionCollector(
                host_os_release_file=str(Path(root) / "missing-os-release"),
                dsm_version_file=str(version),
                status_dir="",
                command_runner=lambda command, timeout: (1, ""),
                docker_request=lambda path: [],
            )
            self.assertEqual(collector.system_identity["source"], "dsm-version")
            self.assertFalse(any(
                item.get("code") == "host_os_unavailable"
                for item in collector.identity_errors
            ))

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

    def test_cpu_details_and_usage_are_bounded_and_include_iowait(self):
        lscpu = json.dumps({"lscpu": [
            {"field": "Architecture:", "data": "x86_64"},
            {"field": "Vendor ID:", "data": "ExampleVendor"},
            {"field": "Model name:", "data": "Example CPU"},
            {"field": "CPU(s):", "data": "4"},
            {"field": "Socket(s):", "data": "1"},
            {"field": "Core(s) per socket:", "data": "2"},
            {"field": "Thread(s) per core:", "data": "2"},
            {"field": "CPU max MHz:", "data": "3400.0"},
            {"field": "L3 cache:", "data": "4 MiB"},
        ]})
        with tempfile.TemporaryDirectory() as root:
            cpuinfo = Path(root) / "cpuinfo"
            cpuinfo.write_text("cpu MHz\t\t: 1200.0\ncpu MHz\t\t: 1800.0\n", encoding="utf-8")
            details, error = collect_cpu_details(
                lambda command, timeout: (0, lscpu), str(cpuinfo)
            )
        self.assertIsNone(error)
        self.assertEqual(details["architecture"], "x86_64")
        self.assertEqual(details["logical_cpus"], 4)
        self.assertEqual(details["current_mhz"], 1500.0)
        self.assertEqual(details["l3_cache"], "4 MiB")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "stat"
            path.write_text("cpu  100 10 20 800 30 4 6 2\n", encoding="utf-8")

            def advance(_seconds):
                path.write_text("cpu  130 10 40 860 45 5 10 5\n", encoding="utf-8")

            usage, usage_error = collect_cpu_usage(str(path), advance)
        self.assertIsNone(usage_error)
        self.assertGreater(usage["iowait_percent"], 0)
        self.assertAlmostEqual(usage["total_percent"], 100 - usage["idle_percent"], places=1)

    def test_memory_details_reports_buffers_cache_and_swap(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meminfo"
            path.write_text(
                "MemTotal:       1000 kB\nMemAvailable:    400 kB\nMemFree: 200 kB\n"
                "Buffers: 100 kB\nCached: 250 kB\nSReclaimable: 50 kB\nShmem: 20 kB\n"
                "SwapTotal: 500 kB\nSwapFree: 300 kB\nSwapCached: 10 kB\n",
                encoding="utf-8",
            )
            memory, error = collect_memory_details(str(path))
        self.assertIsNone(error)
        self.assertEqual(memory["total_bytes"], 1000 * 1024)
        self.assertEqual(memory["used_bytes"], 600 * 1024)
        self.assertEqual(memory["buffers_bytes"], 100 * 1024)
        self.assertEqual(memory["cached_bytes"], 280 * 1024)
        self.assertEqual(memory["swap_used_bytes"], 200 * 1024)

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

    def test_missing_hermes_snapshot_is_an_optional_agent_not_an_error(self):
        snapshot = read_hermes_snapshot("/does/not/exist")
        self.assertEqual(snapshot["profiles"], [])
        self.assertFalse(snapshot["stale"])
        self.assertIsNone(snapshot["error"])

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

    def test_smartctl_json_device_open_failure_is_not_reported_as_unknown(self):
        output = json.dumps(
            {
                "smartctl": {
                    "exit_status": 2,
                    "messages": [{"severity": "error", "string": "device open failed"}],
                }
            }
        )
        smart, error = collect_smart(
            "/dev/example", SmartRunner(output, json_returncode=2)
        )
        self.assertIsNone(smart)
        self.assertEqual(error["code"], "smartctl_unavailable")

    def test_smartctl_ata_command_warning_keeps_usable_json_snapshot(self):
        data = fixture_json("smart-normal.json")
        data["smartctl"] = {"exit_status": 4}
        smart, error = collect_smart(
            "/dev/example", SmartRunner(json.dumps(data), json_returncode=4)
        )
        self.assertIsNone(error)
        self.assertEqual(smart["source"], "smartctl-json")
        self.assertEqual(smart["health"], "passed")

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

    def test_multiple_smart_devices_are_independent_and_do_not_pick_legacy_first(self):
        first = fixture_json("smart-normal.json")
        second = fixture_json("smart-normal.json")
        set_smart_temperature(second, 44)
        runner = MultiSmartRunner({
            "/dev/sda": json.dumps(first),
            "/dev/sdb": json.dumps(second),
        })
        records, error = collect_smart_devices(
            [{"path": "/dev/sda", "type": "sat"}, {"path": "/dev/sdb"}], runner
        )
        self.assertEqual(len(records), 2)
        self.assertIsNone(error)
        self.assertEqual([record[1]["device"] for record in records], ["/dev/sda", "/dev/sdb"])

        payload = collect_hardware(
            "Example CPU", smart_devices=[{"path": "/dev/sda"}, {"path": "/dev/sdb"}],
            command_runner=runner, sys_block_root="/no-sys-block", now=FIXED_NOW,
        )
        self.assertEqual(payload["disk_smart_status"], "passed")
        self.assertIsNone(payload["disk_device"])
        self.assertIsNone(payload["disk_temperature"])
        self.assertEqual(payload["storage"]["summary"]["physical_disk_count"], 2)
        self.assertEqual(payload["storage"]["summary"]["smart_passed"], 2)

    def test_explicit_smart_allowlist_keeps_usb_and_boot_but_excludes_zram(self):
        smart = fixture_json("smart-normal.json")

        def runner(command, timeout):
            if command[:1] == ["lsblk"]:
                return 0, json.dumps({"blockdevices": [
                    {"name": "sda", "kname": "sda", "type": "disk", "size": 1000},
                    {"name": "sdb", "kname": "sdb", "type": "disk", "size": 2000},
                    {"name": "zram0", "kname": "zram0", "type": "disk", "size": 3000},
                    {"name": "sdu", "kname": "sdu", "type": "disk", "size": 4000, "tran": "usb"},
                    {"name": "synoboot", "kname": "synoboot", "type": "disk", "size": 5000},
                ]})
            if "-j" in command:
                return 0, json.dumps(smart)
            return 0, "SMART overall-health self-assessment test result: PASSED\n"

        payload = collect_hardware(
            "Example CPU",
            smart_devices=[{"path": "/dev/sda"}],
            command_runner=runner,
            sys_block_root="/no-sys-block",
            now=FIXED_NOW,
        )
        self.assertEqual(
            [disk["id"] for disk in payload["storage"]["physical_disks"]],
            ["sda", "sdu", "synoboot"],
        )

    def test_explicit_empty_smart_allowlist_keeps_topology_without_an_error(self):
        runner = MultiSmartRunner({})
        records, error = collect_smart_devices([], runner)
        self.assertEqual(records, [])
        self.assertIsNone(error)

        payload = collect_hardware(
            "Example CPU", smart_devices=[], command_runner=runner,
            sys_block_root="/no-sys-block", now=FIXED_NOW,
        )
        self.assertIsNone(payload["storage"]["error"])
        self.assertEqual(payload["storage"]["summary"]["physical_disk_count"], 2)
        self.assertTrue(all(
            disk["collection_status"] == "unsupported"
            for disk in payload["storage"]["physical_disks"]
        ))

    def test_explicit_primary_smart_device_restores_legacy_projection(self):
        first = fixture_json("smart-normal.json")
        second = fixture_json("smart-normal.json")
        set_smart_temperature(second, 44)
        runner = MultiSmartRunner({
            "/dev/sda": json.dumps(first),
            "/dev/sdb": json.dumps(second),
        })
        payload = collect_hardware(
            "Example CPU", smart_devices=[{"path": "/dev/sda"}, {"path": "/dev/sdb"}],
            primary_smart_device="/dev/sdb", command_runner=runner,
            sys_block_root="/no-sys-block", now=FIXED_NOW,
        )
        self.assertEqual(payload["disk_device"], "/dev/sdb")
        self.assertEqual(payload["disk_temperature"]["current"], 44.0)

    def test_block_graph_resolves_synthetic_lvm_without_name_heuristics(self):
        graph = build_block_device_graph(
            {
                "blockdevices": [
                    {
                        "name": "sda", "kname": "sda", "type": "disk", "size": 1000,
                        "children": [{
                            "name": "sda3", "kname": "sda3", "pkname": "sda", "type": "part",
                            "children": [{
                                "name": "dm-0", "kname": "dm-0", "pkname": "sda3", "type": "lvm",
                            }],
                        }],
                    }
                ]
            },
            sys_block_root="/no-sys-block",
        )
        self.assertEqual(resolve_backing_physical_disks("/dev/dm-0", graph), ["sda"])

    def test_explicit_filesystem_probe_reports_usage_and_lvm_backing_disk(self):
        graph = build_block_device_graph(
            {
                "blockdevices": [
                    {
                        "name": "sda", "kname": "sda", "type": "disk", "size": 1000,
                        "children": [{
                            "name": "sda3", "kname": "sda3", "pkname": "sda", "type": "part",
                            "children": [{
                                "name": "dm-0", "kname": "dm-0", "pkname": "sda3", "type": "lvm",
                            }],
                        }],
                    }
                ]
            },
            sys_block_root="/no-sys-block",
        )

        def runner(command, timeout):
            self.assertEqual(command[:3], ["findmnt", "--json", "--target"])
            return 0, json.dumps({
                "filesystems": [{"source": "/dev/dm-0", "fstype": "ext4"}]
            })

        class SyntheticStatvfs(object):
            f_frsize = 1024
            f_bsize = 1024
            f_blocks = 1000
            f_bavail = 250
            f_bfree = 250

        filesystems, error = collect_filesystems(
            [{"mountpoint": "/", "probe_path": "/host-storage/root"}],
            graph,
            command_runner=runner,
            statvfs_func=lambda path: SyntheticStatvfs(),
        )
        self.assertIsNone(error)
        self.assertEqual(filesystems[0]["backing_disk_ids"], ["sda"])
        self.assertEqual(filesystems[0]["stack_type"], "lvm")
        self.assertEqual(filesystems[0]["used_bytes"], 750 * 1024)
        self.assertEqual(filesystems[0]["usage_percent"], 75.0)

    def test_filesystem_probe_normalizes_bind_mount_source_to_its_block_device(self):
        graph = build_block_device_graph(
            {
                "blockdevices": [
                    {
                        "name": "sda", "kname": "sda", "type": "disk", "size": 1000,
                        "children": [{"name": "sda1", "kname": "sda1", "pkname": "sda", "type": "part"}],
                    }
                ]
            },
            sys_block_root="/no-sys-block",
        )

        def runner(command, timeout):
            self.assertEqual(command[:3], ["findmnt", "--json", "--target"])
            return 0, json.dumps({
                "filesystems": [{"source": "/dev/sda1[/srv/data]", "fstype": "ext4"}]
            })

        class SyntheticStatvfs(object):
            f_frsize = 1024
            f_bsize = 1024
            f_blocks = 1000
            f_bavail = 250
            f_bfree = 250

        filesystems, error = collect_filesystems(
            [{"mountpoint": "/data", "probe_path": "/host-storage/data"}],
            graph,
            command_runner=runner,
            statvfs_func=lambda path: SyntheticStatvfs(),
        )
        self.assertIsNone(error)
        self.assertEqual(filesystems[0]["source"], "/dev/sda1")
        self.assertEqual(filesystems[0]["backing_disk_ids"], ["sda"])
        self.assertEqual(filesystems[0]["stack_type"], "plain")

    def test_filesystem_usage_counts_reserved_blocks_as_used(self):
        graph = build_block_device_graph(
            {"blockdevices": [{"name": "sda", "kname": "sda", "type": "disk", "size": 1000}]},
            sys_block_root="/no-sys-block",
        )

        class SyntheticStatvfs(object):
            f_frsize = 1024
            f_bsize = 1024
            f_blocks = 1000
            f_bavail = 250
            f_bfree = 300

        filesystems, error = collect_filesystems(
            [{"mountpoint": "/data", "probe_path": "/host-storage/data"}], graph,
            command_runner=lambda command, timeout: (0, json.dumps({"filesystems": [{"source": "/dev/sda", "fstype": "ext4"}]})),
            statvfs_func=lambda path: SyntheticStatvfs(),
        )
        self.assertIsNone(error)
        self.assertEqual(filesystems[0]["available_bytes"], 250 * 1024)
        self.assertEqual(filesystems[0]["used_bytes"], 700 * 1024)
        self.assertEqual(filesystems[0]["usage_percent"], 70.0)

    def test_filesystem_probe_retains_safe_nested_device_mapper_source(self):
        graph = build_block_device_graph(
            {
                "blockdevices": [
                    {
                        "name": "sda", "kname": "sda", "type": "disk", "size": 1000,
                        "children": [{
                            "name": "vg-root", "kname": "dm-0",
                            "path": "/dev/mapper/vg-root", "pkname": "sda", "type": "lvm",
                        }],
                    }
                ]
            },
            sys_block_root="/no-sys-block",
        )

        def runner(command, timeout):
            self.assertEqual(command[:3], ["findmnt", "--json", "--target"])
            return 0, json.dumps({
                "filesystems": [{"source": "/dev/mapper/vg-root", "fstype": "ext4"}]
            })

        class SyntheticStatvfs(object):
            f_frsize = 1024
            f_bsize = 1024
            f_blocks = 1000
            f_bavail = 250
            f_bfree = 250

        filesystems, error = collect_filesystems(
            [{"mountpoint": "/mnt/My Drive/数据", "probe_path": "/host-storage/data"}],
            graph,
            command_runner=runner,
            statvfs_func=lambda path: SyntheticStatvfs(),
        )
        self.assertIsNone(error)
        self.assertEqual(filesystems[0]["source"], "/dev/mapper/vg-root")
        self.assertEqual(filesystems[0]["backing_disk_ids"], ["sda"])
        self.assertEqual(filesystems[0]["stack_type"], "lvm")

    def test_filesystem_probe_caps_backing_disks_and_classifies_btrfs(self):
        graph = {
            "aliases": {"/dev/md0": "md0", "/dev/sda1": "sda1"},
            "nodes": {
                "md0": {"type": "raid1", "slaves": ["disk%02d" % index for index in range(17)]},
                "sda1": {"type": "part", "parent": "sda"},
                "sda": {"type": "disk"},
                **{"disk%02d" % index: {"type": "disk"} for index in range(17)},
            },
        }

        def runner(command, timeout):
            source = "/dev/md0" if command[-1].endswith("raid") else "/dev/sda1"
            fs_type = "ext4" if source == "/dev/md0" else "btrfs"
            return 0, json.dumps({"filesystems": [{"source": source, "fstype": fs_type}]})

        class SyntheticStatvfs(object):
            f_frsize = 1024
            f_bsize = 1024
            f_blocks = 1000
            f_bavail = 250
            f_bfree = 250

        filesystems, error = collect_filesystems(
            [
                {"mountpoint": "/raid", "probe_path": "/host-storage/raid"},
                {"mountpoint": "/btrfs", "probe_path": "/host-storage/btrfs"},
            ],
            graph,
            command_runner=runner,
            statvfs_func=lambda path: SyntheticStatvfs(),
        )
        self.assertIsNone(error)
        self.assertEqual(len(filesystems[0]["backing_disk_ids"]), 16)
        self.assertEqual(filesystems[0]["stack_type"], "mdraid")
        self.assertEqual(filesystems[1]["stack_type"], "btrfs")
        self.assertEqual(filesystems[1]["backing_disk_ids"], [])

    def test_filesystem_probe_preserves_configured_mountpoint_spacing(self):
        graph = build_block_device_graph(
            {"blockdevices": [{"name": "sda", "kname": "sda", "type": "disk"}]},
            sys_block_root="/no-sys-block",
        )

        class SyntheticStatvfs(object):
            f_frsize = 1024
            f_bsize = 1024
            f_blocks = 1000
            f_bavail = 250
            f_bfree = 250

        filesystems, error = collect_filesystems(
            [{"mountpoint": "/mnt/My  Drive", "probe_path": "/host-storage/data"}],
            graph,
            command_runner=lambda command, timeout: (0, json.dumps({"filesystems": [{
                "source": "/dev/sda", "fstype": "ext4"
            }]})),
            statvfs_func=lambda path: SyntheticStatvfs(),
        )
        self.assertIsNone(error)
        self.assertEqual(filesystems[0]["mountpoint"], "/mnt/My  Drive")

    def test_hardware_keeps_probed_backing_disk_inside_bounded_inventory(self):
        disks = [
            {"name": "disk%02d" % index, "kname": "disk%02d" % index, "type": "disk"}
            for index in range(65)
        ]

        def runner(command, timeout):
            if command[:1] == ["lsblk"]:
                return 0, json.dumps({"blockdevices": disks})
            if command[:3] == ["findmnt", "--json", "--target"]:
                return 0, json.dumps({"filesystems": [{
                    "source": "/dev/disk64", "fstype": "ext4"
                }]})
            raise AssertionError("unexpected command: %r" % (command,))

        class SyntheticStatvfs(object):
            f_frsize = 1024
            f_bsize = 1024
            f_blocks = 1000
            f_bavail = 250
            f_bfree = 250

        payload = collect_hardware(
            "Example CPU", smart_devices=[], command_runner=runner,
            filesystem_probes=[{"mountpoint": "/data", "probe_path": "/host-storage/data"}],
            sys_block_root="/no-sys-block", statvfs_func=lambda path: SyntheticStatvfs(),
            now=FIXED_NOW,
        )
        reported = {disk["id"] for disk in payload["storage"]["physical_disks"]}
        self.assertEqual(len(reported), 64)
        self.assertIn("disk64", reported)
        self.assertEqual(
            payload["storage"]["filesystems"][0]["backing_disk_ids"], ["disk64"]
        )

    def test_nvme_controller_smart_target_reuses_its_namespace_topology_disk(self):
        smart = fixture_json("smart-normal.json")

        def runner(command, timeout):
            if command[:1] == ["lsblk"]:
                return 0, json.dumps({
                    "blockdevices": [{
                        "name": "nvme0n1", "kname": "nvme0n1", "type": "disk", "size": 1000,
                    }]
                })
            if "-j" in command:
                return 0, json.dumps(smart)
            return 0, "SMART overall-health self-assessment test result: PASSED\n"

        payload = collect_hardware(
            "Example CPU", smart_devices=[{"path": "/dev/nvme0", "type": "nvme"}],
            command_runner=runner, sys_block_root="/no-sys-block", now=FIXED_NOW,
        )
        disks = payload["storage"]["physical_disks"]
        self.assertEqual([disk["id"] for disk in disks], ["nvme0n1"])
        self.assertEqual(disks[0]["device"], "/dev/nvme0n1")
        self.assertEqual(payload["storage"]["summary"]["physical_disk_count"], 1)
        self.assertEqual(payload["storage"]["summary"]["smart_passed"], 1)

    def test_client_build_only_projects_explicit_build_environment(self):
        self.assertIsNone(collect_client_build({}))
        self.assertEqual(
            collect_client_build({
                "HERMESSTATUS_CLIENT_VERSION": "2.3-preview",
                "HERMESSTATUS_CLIENT_REVISION": "abcdef0123abcdef0123abcdef0123abcdef0123",
                "HERMESSTATUS_CLIENT_BUILD_TIME": "2026-08-11T00:00:00Z",
                "HERMESSTATUS_CLIENT_PROTOCOL": "device_v2",
            }),
            {
                "version": "2.3-preview",
                "revision": "abcdef0123abcdef0123abcdef0123abcdef0123",
                "build_time": "2026-08-11T00:00:00Z",
                "protocol": "device_v2",
            },
        )
        self.assertIsNone(
            collect_client_build({
                "HERMESSTATUS_CLIENT_VERSION": "2.3-preview",
                "HERMESSTATUS_CLIENT_REVISION": "unknown",
                "HERMESSTATUS_CLIENT_PROTOCOL": "device_v2",
            })
        )

    def test_extension_payload_exposes_client_build_at_the_root(self):
        build = {"version": "2.3-preview", "revision": "abcdef012345", "protocol": "device_v2", "build_time": None}
        collector = HostExtensionCollector(
            host_os_release_file=str(FIXTURES / "os-release"),
            client_build=build,
            status_dir="",
            command_runner=lambda command, timeout: (0, ""),
            docker_request=lambda path: [],
        )
        payload = collector.extension_payload()
        self.assertEqual(payload["client_build"], build)
        self.assertNotIn("client_build", payload["hardware"])

    def test_extension_payload_omits_unavailable_client_build(self):
        collector = HostExtensionCollector(
            host_os_release_file=str(FIXTURES / "os-release"),
            client_build=None,
            status_dir="",
            command_runner=lambda command, timeout: (0, ""),
            docker_request=lambda path: [],
        )
        self.assertNotIn("client_build", collector.extension_payload())

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

    def test_hermes_snapshot_reader_allows_missing_agent_but_degrades_corrupt_data(self):
        missing = read_hermes_snapshot("/does/not/exist")
        self.assertEqual(missing["profiles"], [])
        self.assertFalse(missing["stale"])
        self.assertIsNone(missing["error"])
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
            "easytier": not_configured_easytier(),
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
        self.assertNotIn("client_build", update)

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
