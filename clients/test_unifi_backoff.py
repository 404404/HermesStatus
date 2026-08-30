import threading
import time
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from host_collector import HostExtensionCollector


class FakeUniFi:
    class config:
        profile_id = "udw"
        interval_seconds = 60

    def __init__(self, outcomes=None, started=None, release=None):
        self.outcomes = list(outcomes or [])
        self.calls = 0
        self.started = started
        self.release = release

    def collect(self):
        self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            self.release.wait(2)
        return self.outcomes.pop(0)


def failure(code="ssh_auth_failure"):
    return {
        "configured": True, "profile": "udw",
        "transport": {"status": "unavailable"},
        "stale": True,
        "error": {"code": code},
    }


def success():
    return {
        "configured": True, "profile": "udw",
        "transport": {"status": "available"},
        "stale": False,
        "error": None,
    }


def make_collector(fake, clock):
    return HostExtensionCollector(
        host_os_release_file=str(Path(__file__).resolve().parent / "testdata" / "os-release"),
        status_dir="",
        command_runner=lambda command, timeout: (0, ""),
        docker_request=lambda path: [],
        unifi_collector=fake,
        unifi_clock=lambda: clock[0],
    )


class UniFiBackoffTests(unittest.TestCase):
    def test_auth_failure_uses_bounded_cooldown_and_success_resets(self):
        clock = [0.0]
        fake = FakeUniFi([failure(), failure(), success()])
        collector = make_collector(fake, clock)

        collector.collect_unifi_once()
        self.assertEqual(fake.calls, 1)
        self.assertEqual(collector._unifi_retry_after, 300.0)

        collector.collect_unifi_once()
        self.assertEqual(fake.calls, 1)
        clock[0] = 300.0
        collector.collect_unifi_once()
        self.assertEqual(fake.calls, 2)
        self.assertEqual(collector._unifi_retry_after, 1200.0)

        collector.collect_unifi_once()
        self.assertEqual(fake.calls, 2)
        clock[0] = 1200.0
        collector.collect_unifi_once()
        self.assertEqual(fake.calls, 3)
        self.assertEqual(collector._unifi_failure_streak, 0)
        self.assertEqual(collector._unifi_retry_after, 0.0)

    def test_host_key_configuration_and_host_key_failure_backoff(self):
        clock = [0.0]
        fake = FakeUniFi([failure("host_key_configuration"), failure("host_key_failure")])
        collector = make_collector(fake, clock)
        collector.collect_unifi_once()
        self.assertEqual(collector._unifi_retry_after, 300.0)
        clock[0] = 300.0
        collector.collect_unifi_once()
        self.assertEqual(fake.calls, 2)
        self.assertEqual(collector._unifi_retry_after, 1200.0)

    def test_concurrent_trigger_does_not_start_second_acquisition(self):
        started = threading.Event()
        release = threading.Event()
        fake = FakeUniFi([success()], started=started, release=release)
        collector = make_collector(fake, [0.0])
        first = threading.Thread(target=collector.collect_unifi_once)
        first.start()
        self.assertTrue(started.wait(1))
        collector.collect_unifi_once()
        self.assertEqual(fake.calls, 1)
        release.set()
        first.join(2)
        self.assertFalse(first.is_alive())


if __name__ == "__main__":
    unittest.main()
