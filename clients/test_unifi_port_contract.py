import copy
import hashlib
import json
import random
import shutil
import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from unifi_api import MAX_UNIFI_PORTS_PER_DEVICE, MAX_UNIFI_SITE_PORT_OBSERVATIONS, _ports
from unifi_model_catalog import (
    CATALOG_BUNDLE_PATH, CATALOG_BUNDLE_SHA256, CATALOG_SOURCE_REVISION,
    ModelCatalogError, load_catalog, project_static_capabilities, resolve_model,
)


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
    def test_qualified_bundle_has_20_models_and_no_fuzzy_resolution(self):
        catalog = load_catalog()
        self.assertEqual(len(catalog), 20)
        for sku in ("UDW", "UCG-Max", "USW-Pro-HD-24", "USW-Pro-HD-24-PoE",
                    "USW-Pro-Max-16", "USW-Pro-Max-16-PoE",
                    "USW-Pro-Max-24", "USW-Pro-Max-24-PoE",
                    "USW-Flex-2.5G-8", "USW-Flex-2.5G-8-PoE"):
            self.assertIn(sku, catalog)
        aliases = (
            ("api_model", "UniFi Dream Wall", "UDW"),
            ("ssh_model", "Annapurna Labs Alpine V2 UBNT", "UDW"),
            ("sysid", "0xea2a", "UDW"),
            ("api_model", "UCG Max", "UCG-Max"),
            ("ssh_model", "Qualcomm Technologies, Inc. IPQ5332/AP-MI03.1", "UCG-Max"),
            ("api_model", "USW Flex Mini", "USW-Flex-Mini"),
        )
        for kind, value, expected_sku in aliases:
            with self.subTest(kind=kind, value=value):
                self.assertEqual(resolve_model(catalog, value, kind=kind)["canonical_sku"], expected_sku)
        self.assertIsNone(resolve_model(catalog, "unknown-runtime-model"))
        self.assertIsNone(resolve_model(catalog, "Cloud Gateway Max"))
        self.assertIsNone(resolve_model(catalog, "UCG-Max"))
        self.assertIsNone(resolve_model(catalog, "UCG-Max", kind="not-an-identifier"))
        self.assertEqual(resolve_model(catalog, "UCG-Max", explicit_sku=True)["canonical_sku"], "UCG-Max")

    def test_catalog_revision_and_checksum_are_pinned(self):
        self.assertEqual(CATALOG_SOURCE_REVISION, "83a6c841d29775803d892ab797821c7f061ccbde")
        self.assertEqual(CATALOG_BUNDLE_SHA256, "234df9f3174997aa8d11c0da98a7504725455b1df3668654d2f78e1030f13043")
        manifest = CATALOG_BUNDLE_PATH.with_name("catalog.sha256").read_text(encoding="ascii").strip()
        self.assertEqual(manifest, CATALOG_BUNDLE_SHA256 + "  catalog.json")

    def test_static_projection_preserves_bundle_shape_without_runtime_aliases(self):
        catalog = load_catalog()
        projection = project_static_capabilities(catalog["UDW"])
        self.assertEqual(projection["canonical_sku"], "UDW")
        self.assertEqual(projection["processor"]["model"], "Annapurna AL324")
        self.assertEqual(projection["power"]["psu_unit_capacity_w"], 550)
        self.assertEqual(projection["power"]["controller_reference_capacity_w"], 550)
        self.assertEqual(projection["power"]["max_device_consumption_w"], 532)
        self.assertEqual(projection["power"]["absolute_max_poe_budget_w"], 420)
        self.assertEqual(len(projection["ports"]["items"]), 20)
        self.assertEqual(projection["storage"]["items"][0]["type"], "emmc")
        self.assertNotIn("runtime_identifiers", projection)
        projection["ports"]["items"][0]["label"] = "changed"
        self.assertNotEqual(catalog["UDW"]["ports"]["items"][0]["label"], "changed")

    def test_ssh_alias_does_not_override_static_processor_model(self):
        catalog = load_catalog()
        model = resolve_model(catalog, "Qualcomm Technologies, Inc. IPQ5332/AP-MI03.1", kind="ssh_model")
        self.assertEqual(model["canonical_sku"], "UCG-Max")
        self.assertEqual(model["processor"]["model"], "Qualcomm IPQ5322")
        self.assertEqual(project_static_capabilities(model)["processor"]["model"], "Qualcomm IPQ5322")

    def test_catalog_ports_have_neutral_labels_and_typed_connectors(self):
        catalog = load_catalog()
        for sku in ("USW-Flex", "USW-Flex-2.5G-8-PoE", "U6-IW", "U6-Enterprise-IW", "U6-Mesh", "UAP-AC-M"):
            ports = project_static_capabilities(catalog[sku])["ports"]["items"]
            self.assertEqual([port["label"] for port in ports], [f"Port {index}" for index in range(1, len(ports) + 1)])
            self.assertTrue(all(port["connector"] in {"rj45", "sfp", "sfp_plus", "sfp28", "qsfp28", "other"} for port in ports))

    def test_catalog_allows_explicitly_unknown_port_roles(self):
        catalog = load_catalog()
        udw = project_static_capabilities(catalog["UDW"])
        self.assertEqual(udw["ports"]["items"][-1]["roles"], [])

    def test_catalog_static_poe_budgets_are_not_runtime_observations(self):
        catalog = load_catalog()
        expected = {
            "UDW": (420, 421.6),
            "US-XG-6POE": (170, 240),
            "USW-Enterprise-8-PoE": (120, 240),
            "USW-Flex": (46, 120),
            "USW-Flex-2.5G-8-PoE": (196, 480),
            "USW-Pro-HD-24-PoE": (600, 1440),
            "USW-Pro-Max-16-PoE": (180, 600),
            "USW-Pro-Max-24-PoE": (400, 1200),
        }
        for sku, (budget, port_sum) in expected.items():
            projection = project_static_capabilities(catalog[sku])
            self.assertEqual(projection["power"]["absolute_max_poe_budget_w"], budget)
            self.assertEqual(
                sum(port["poe_max_power_w"] for port in projection["ports"]["items"] if port["poe_out"] is True),
                port_sum,
            )
            self.assertNotEqual(port_sum, budget)

    def test_functional_port_roles_do_not_replace_neutral_labels(self):
        catalog = load_catalog()
        flex = project_static_capabilities(catalog["USW-Flex"])["ports"]["items"]
        self.assertEqual((flex[0]["label"], flex[0]["connector"]), ("Port 1", "rj45"))
        self.assertTrue(flex[0]["poe_in"])
        flex_25g = project_static_capabilities(catalog["USW-Flex-2.5G-8-PoE"])["ports"]["items"]
        self.assertEqual((flex_25g[8]["label"], flex_25g[8]["connector"]), ("Port 9", "rj45"))
        self.assertTrue(flex_25g[8]["poe_in"])
        self.assertEqual((flex_25g[9]["label"], flex_25g[9]["connector"]), ("Port 10", "sfp_plus"))
        flex_25g_input = project_static_capabilities(catalog["USW-Flex-2.5G-8"])["ports"]["items"]
        self.assertTrue(flex_25g_input[8]["poe_in"])
        self.assertEqual(flex_25g_input[8]["poe_standard"], "poe+")
        u6_iw = project_static_capabilities(catalog["U6-IW"])["ports"]["items"]
        self.assertIn("poe_passthrough", u6_iw[0]["roles"])
        self.assertIn("data_in", u6_iw[4]["roles"])
        self.assertEqual([port["label"] for port in u6_iw], [f"Port {index}" for index in range(1, 6)])

    def test_power_projection_keeps_profiles_and_unknown_budgets(self):
        catalog = load_catalog()
        flex = project_static_capabilities(catalog["USW-Flex-2.5G-8-PoE"])
        profiles = {item["id"]: item for item in flex["power"]["power_profiles"]}
        self.assertEqual(profiles["dc-60w"]["status"], "verified")
        self.assertEqual(profiles["dc-60w"]["selection_mode"], "controller_manual")
        self.assertEqual(profiles["dc-60w"]["input_method"], "dc_adapter")
        self.assertEqual(profiles["dc-60w"]["input_capacity_w"], 60)
        self.assertIsNone(profiles["dc-60w"]["poe_budget_w"])
        self.assertGreaterEqual(flex["power"]["absolute_max_poe_budget_w"], max(
            item["poe_budget_w"] for item in profiles.values() if item["poe_budget_w"] is not None
        ))
        non_poe = project_static_capabilities(catalog["USW-Pro-Max-16"])
        self.assertEqual(non_poe["power"]["absolute_max_poe_budget_w"], 0)
        self.assertFalse(any(port["poe_out"] is True for port in non_poe["ports"]["items"]))

    def test_candidate_alias_is_not_a_production_resolution(self):
        catalog = load_catalog()
        candidate = copy.deepcopy(catalog["UCG-Max"])
        candidate["runtime_identifiers"]["api_model"] = [{
            "value": "candidate-api-model", "status": "candidate",
            "provenance": "qualified_controller", "evidence_id": "fixture-candidate"
        }]
        synthetic = dict(catalog)
        synthetic[candidate["canonical_sku"]] = candidate
        self.assertIsNone(resolve_model(synthetic, "candidate-api-model"))
        verified = copy.deepcopy(candidate)
        verified["runtime_identifiers"]["api_model"][0]["status"] = "verified"
        synthetic[verified["canonical_sku"]] = verified
        self.assertEqual(resolve_model(synthetic, "candidate-api-model")["canonical_sku"], "UCG-Max")
        self.assertIsNone(resolve_model(synthetic, "candidate-api-model", kind="sysid"))

    def test_loader_rejects_duplicate_verified_alias_and_unexpected_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            shutil.copyfile(ROOT / "unifi_catalog" / "catalog.json", source / "catalog.json")
            bundle = json.loads((source / "catalog.json").read_text(encoding="utf-8"))
            alias = {
                "value": "same-qualified-api",
                "status": "verified",
                "provenance": "qualified_controller",
                "evidence_id": "runtime-test",
            }
            for model in bundle["models"][:2]:
                model["runtime_identifiers"]["api_model"] = [copy.deepcopy(alias)]
            raw = json.dumps(bundle, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            (source / "catalog.json").write_bytes(raw)
            (source / "catalog.sha256").write_text(hashlib.sha256(raw).hexdigest() + "  catalog.json\n", encoding="ascii")
            with self.assertRaisesRegex(ModelCatalogError, "duplicate verified runtime alias ownership"):
                load_catalog(source)

            bundle = json.loads((ROOT / "unifi_catalog" / "catalog.json").read_text(encoding="utf-8"))
            bundle["models"][0]["unexpected"] = True
            raw = json.dumps(bundle, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            (source / "catalog.json").write_bytes(raw)
            (source / "catalog.sha256").write_text(hashlib.sha256(raw).hexdigest() + "  catalog.json\n", encoding="ascii")
            with self.assertRaisesRegex(ModelCatalogError, "invalid model"):
                load_catalog(source)

    def test_schema_version_and_checksum_are_compatibility_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            shutil.copyfile(ROOT / "unifi_catalog" / "catalog.json", source / "catalog.json")
            shutil.copyfile(ROOT / "unifi_catalog" / "catalog.sha256", source / "catalog.sha256")
            bundle = json.loads((source / "catalog.json").read_text(encoding="utf-8"))
            bundle["schema_version"] = 2
            raw = json.dumps(bundle, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            (source / "catalog.json").write_bytes(raw)
            (source / "catalog.sha256").write_text(hashlib.sha256(raw).hexdigest() + "  catalog.json\n", encoding="ascii")
            with self.assertRaisesRegex(ModelCatalogError, "unsupported catalog schema_version"):
                load_catalog(source)
            (source / "catalog.sha256").write_text("0" * 64 + "  catalog.json\n", encoding="ascii")
            with self.assertRaisesRegex(ModelCatalogError, "checksum mismatch"):
                load_catalog(source)


if __name__ == "__main__":
    unittest.main()
