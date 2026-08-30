import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from unifi_api import MAX_UNIFI_PORTS_PER_DEVICE, MAX_UNIFI_SITE_PORT_OBSERVATIONS, _ports
from unifi_model_catalog import load_catalog, resolve_model


class UniFiPortContractTests(unittest.TestCase):
    def _devices(self, count):
        return [
            {"id": f"device-{index:02d}", "model": f"unknown-{index}", "name": f"Device {index}", "state": "ONLINE"}
            for index in range(count)
        ]

    def _legacy(self, devices, counts):
        return {
            "data": [
                {
                    "device_id": device["id"],
                    "port_table": [{"port_idx": port_index, "up": port_index % 2 == 0} for port_index in range(1, count + 1)],
                }
                for device, count in zip(devices, counts)
            ]
        }

    def test_real_sample_shape_is_accepted_with_site_wide_bound(self):
        devices = self._devices(11)
        counts = [6, 5, 5, 5, 5, 28, 5, 10, 18, 5, 5]
        records, _ = _ports(self._legacy(devices, counts), devices[0], {}, 1.0, devices=devices)
        self.assertEqual(len(records), 97)
        self.assertEqual(len({item["device_id"] for item in records}), 11)
        self.assertEqual(
            [sum(item["device_id"] == device["id"] for item in records) for device in devices],
            counts,
        )
        self.assertEqual(max(item["port_idx"] for item in records), 28)
        self.assertEqual(
            [(item["device_id"], item["port_idx"]) for item in records],
            sorted((item["device_id"], item["port_idx"]) for item in records),
        )

    def test_survivors_are_independent_of_api_device_and_port_order(self):
        devices = self._devices(11)
        counts = [6, 5, 5, 5, 5, 28, 5, 10, 18, 5, 5]
        baseline, _ = _ports(self._legacy(devices, counts), devices[0], {}, 1.0, devices=devices)
        shuffled_devices = list(reversed(devices))
        shuffled_legacy = self._legacy(shuffled_devices, list(reversed(counts)))
        for record in shuffled_legacy["data"]:
            random.Random(record["device_id"]).shuffle(record["port_table"])
        shuffled, _ = _ports(shuffled_legacy, shuffled_devices[-1], {}, 1.0, devices=shuffled_devices)
        self.assertEqual(
            [(item["device_id"], item["port_idx"]) for item in baseline],
            [(item["device_id"], item["port_idx"]) for item in shuffled],
        )

    def test_client_applies_site_wide_bound_after_each_device_bound(self):
        devices = self._devices(5)
        records, _ = _ports(self._legacy(devices, [64, 64, 64, 64, 1]), devices[0], {}, 1.0, devices=devices)
        self.assertEqual(MAX_UNIFI_PORTS_PER_DEVICE, 64)
        self.assertEqual(len(records), MAX_UNIFI_SITE_PORT_OBSERVATIONS)
        self.assertEqual(MAX_UNIFI_SITE_PORT_OBSERVATIONS, 256)


class UniFiModelCatalogTests(unittest.TestCase):
    def test_catalog_has_exact_verified_models_and_no_fuzzy_resolution(self):
        catalog = load_catalog()
        for sku in ("UDW", "UCG-Max", "U6-Mesh", "USW-Flex-Mini", "USW-Pro-HD-24"):
            self.assertIn(sku, catalog)
        self.assertEqual(resolve_model(catalog, "UCG Max")["canonical_sku"], "UCG-Max")
        self.assertEqual(resolve_model(catalog, "U6 Mesh")["canonical_sku"], "U6-Mesh")
        self.assertIsNone(resolve_model(catalog, "U6 Mesh Wireless"))
        self.assertEqual(len(catalog["USW-Flex-Mini"]["ports"]), 5)
        self.assertEqual(len(catalog["U6-Mesh"]["ports"]), 1)
        self.assertEqual(len(catalog["USW-Pro-HD-24"]["ports"]), 28)
        self.assertEqual(catalog["UDW"]["storage"]["sata_ssd"]["capacity_bytes"], 128000000000)
        self.assertTrue(catalog["UDW"]["storage"]["tf"]["supported"])
        self.assertEqual(catalog["UDW"]["storage"]["tf"]["present"], "not_populated")
        self.assertFalse(catalog["UDW"]["storage"]["nvme"]["supported"])
        self.assertEqual(catalog["UDW"]["power"], {"psu_slots": 2, "max_power_w": 550})
        self.assertEqual(catalog["UDW"]["ports"][0]["poe_max_power_w"], 15.4)
        self.assertEqual(catalog["UDW"]["ports"][8]["poe_standard"], "poe++")


if __name__ == "__main__":
    unittest.main()
