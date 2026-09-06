import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from unifi_model_catalog import load_catalog, project_static_capabilities, resolve_model


ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "unifi_fixtures" / "ucg-max-runtime-inventory.json"


class UCGMaxCatalogInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_all_ten_runtime_api_models_resolve_exactly(self):
        devices = self.fixture["devices"]
        values = {device["runtime_api_model"] for device in devices}
        self.assertEqual(len(values), 10)
        resolved = {}
        ambiguous = {}
        for value in sorted(values):
            matches = [
                model for model in self.catalog.values()
                if any(
                    alias["status"] == "verified" and alias["value"] == value
                    for alias in model["runtime_identifiers"]["api_model"]
                )
            ]
            if len(matches) == 1:
                resolved[value] = matches[0]["canonical_sku"]
            elif len(matches) > 1:
                ambiguous[value] = matches
        self.assertEqual(len(resolved), 10)
        self.assertEqual(ambiguous, {})
        for device in devices:
            model = resolve_model(
                self.catalog,
                device["runtime_api_model"],
                kind="api_model",
            )
            self.assertIsNotNone(model)
            self.assertEqual(model["canonical_sku"], device["expected_canonical_sku"])
        self.assertIsNone(resolve_model(self.catalog, "Cloud Gateway Max", kind="api_model"))

    def test_offline_devices_keep_identity_and_static_capability(self):
        offline = [
            device for device in self.fixture["devices"]
            if device["state"] == "offline"
        ]
        self.assertEqual(len(offline), 3)
        for device in offline:
            model = resolve_model(
                self.catalog,
                device["runtime_api_model"],
                kind="api_model",
            )
            self.assertIsNotNone(model)
            static = project_static_capabilities(model)
            self.assertEqual(model["canonical_sku"], device["expected_canonical_sku"])
            self.assertEqual(len(static["ports"]["items"]), device["catalog_physical_port_count"])
            self.assertEqual(device["state"], "offline")

    def test_physical_ports_are_catalog_projection_not_runtime_cardinality(self):
        for device in self.fixture["devices"]:
            model = resolve_model(
                self.catalog,
                device["runtime_api_model"],
                kind="api_model",
            )
            static = project_static_capabilities(model)
            self.assertEqual(
                len(static["ports"]["items"]),
                device["catalog_physical_port_count"],
            )
        for model_name in ("AC Mesh", "U6 Mesh"):
            device = next(
                item for item in self.fixture["devices"]
                if item["runtime_api_model"] == model_name
            )
            self.assertEqual(device["interfaces_ports_count"], 0)
            self.assertGreater(device["catalog_physical_port_count"], 0)

    def test_udw_poe_projection_comes_from_pinned_catalog(self):
        udw = project_static_capabilities(self.catalog["UDW"])
        ports = {port["index"]: port for port in udw["ports"]["items"]}
        for index in range(1, 5):
            self.assertEqual(ports[index]["poe_standard"], "poe")
            self.assertEqual(ports[index]["poe_max_power_w"], 15.4)
        for index in range(9, 13):
            self.assertEqual(ports[index]["poe_standard"], "poe++")
            self.assertEqual(ports[index]["poe_max_power_w"], 60)


if __name__ == "__main__":
    unittest.main()
