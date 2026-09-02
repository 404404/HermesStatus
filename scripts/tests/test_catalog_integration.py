from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ACQUIRE = load_module("acquire_unifi_catalog", ROOT / "scripts/acquire_unifi_catalog.py")
PROVENANCE = load_module("validate_image_provenance_27", ROOT / "scripts/validate_image_provenance.py")
PUBLICATION = load_module("candidate_publication", ROOT / "scripts/candidate_publication.py")


REVISION = "a" * 40
CATALOG_REVISION = "b" * 40
CATALOG_SHA256 = "c" * 64
CREATED = "2026-08-31T00:00:00Z"


def client_config():
    return {
        "Entrypoint": ["/app/entrypoint.sh"],
        "Labels": {
            "org.opencontainers.image.title": "HermesStatus Client",
            "org.opencontainers.image.version": "2.7",
            "org.opencontainers.image.revision": REVISION,
            "org.opencontainers.image.created": CREATED,
            "org.opencontainers.image.source": "https://github.com/404404/HermesStatus",
            "org.opencontainers.image.licenses": "MIT",
            "io.hermesstatus.component": "client",
            "io.hermesstatus.unifi.catalog.revision": CATALOG_REVISION,
            "io.hermesstatus.unifi.catalog.schema_version": "1",
            "io.hermesstatus.unifi.catalog.sha256": CATALOG_SHA256,
        },
        "Env": [
            "HERMESSTATUS_CLIENT_VERSION=2.7",
            "HERMESSTATUS_CLIENT_REVISION=" + REVISION,
            "HERMESSTATUS_CLIENT_BUILD_TIME=" + CREATED,
            "HERMESSTATUS_UNIFI_CATALOG_REVISION=" + CATALOG_REVISION,
            "HERMESSTATUS_UNIFI_CATALOG_SCHEMA_VERSION=1",
            "HERMESSTATUS_UNIFI_CATALOG_SHA256=" + CATALOG_SHA256,
        ],
    }


def server_config():
    config = copy.deepcopy(client_config())
    config["Entrypoint"] = ["/usr/local/bin/serverstatus"]
    config["Labels"]["org.opencontainers.image.title"] = "HermesStatus Server"
    config["Labels"]["io.hermesstatus.component"] = "server"
    for key in tuple(config["Labels"]):
        if key.startswith("io.hermesstatus.unifi.catalog."):
            del config["Labels"][key]
    config["Env"] = []
    return config


class CatalogAcquisitionTests(unittest.TestCase):
    def test_lock_and_checked_in_bundle_metadata_are_aligned(self):
        lock = ACQUIRE.load_lock(ROOT / "unifi-catalog.lock.json")
        provenance = json.loads(
            (ROOT / "clients/unifi_catalog/catalog-provenance.json").read_text(encoding="utf-8")
        )
        self.assertEqual(lock["revision"], "813b34eba1dbb7922777897260983ce0189ce39e")
        self.assertEqual(lock["catalog_sha256"], "aa2e5c8f594f1df4e123b32975c0e0dcf333466380013057846381b16288a3b6")
        self.assertEqual(provenance, {
            "catalog_sha256": lock["catalog_sha256"],
            "catalog_schema_version": lock["schema_version"],
            "repository": lock["repository"],
            "revision": lock["revision"],
        })

    def test_checked_in_bundle_matches_locked_build_contract(self):
        bundle_path = ROOT / "clients/unifi_catalog/catalog.json"
        bundle = bundle_path.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory)
            (output / "catalog.json").write_bytes(bundle)
            (output / "catalog.sha256").write_text(
                "aa2e5c8f594f1df4e123b32975c0e0dcf333466380013057846381b16288a3b6  catalog.json\n",
                encoding="ascii",
            )
            (output / "manifest.json").write_text(
                json.dumps({
                    "bundle_sha256": "aa2e5c8f594f1df4e123b32975c0e0dcf333466380013057846381b16288a3b6",
                    "catalog_schema_version": 1,
                    "model_count": len(json.loads(bundle)["models"]),
                }, sort_keys=True),
                encoding="utf-8",
            )
            artifacts = ACQUIRE._verify_build(
                output,
                ACQUIRE.load_lock(ROOT / "unifi-catalog.lock.json"),
            )
            self.assertEqual(artifacts["catalog.json"], bundle)


class CatalogProvenanceTests(unittest.TestCase):
    def test_2_7_candidate_tag_is_supported(self):
        PROVENANCE.validate_candidate_tag("2.7-" + REVISION[:12], "2.7", REVISION)

    def test_catalog_labels_and_runtime_are_required_for_client(self):
        PROVENANCE.validate_catalog_provenance(
            client_config(),
            revision=CATALOG_REVISION,
            schema_version=1,
            sha256=CATALOG_SHA256,
        )
        broken = client_config()
        broken["Labels"] = dict(broken["Labels"])
        broken["Labels"]["io.hermesstatus.unifi.catalog.sha256"] = "d" * 64
        with self.assertRaises(PROVENANCE.ValidationError):
            PROVENANCE.validate_catalog_provenance(
                broken,
                revision=CATALOG_REVISION,
                schema_version=1,
                sha256=CATALOG_SHA256,
            )


class CandidatePublicationTests(unittest.TestCase):
    def params(self):
        return {
            "version": "2.7",
            "revision": REVISION,
            "catalog_revision": CATALOG_REVISION,
            "catalog_schema_version": 1,
            "catalog_sha256": CATALOG_SHA256,
        }

    def test_candidate_tag_must_match_revision(self):
        PUBLICATION.validate_candidate_tag("2.7-" + REVISION[:12], REVISION)
        with self.assertRaises(ValueError):
            PUBLICATION.validate_candidate_tag("2.7-bbbbbbbbbbbb", REVISION)

    def test_both_absent_publish(self):
        self.assertEqual(
            PUBLICATION.classify_publication(
                server_present=False,
                client_present=False,
                server_labels=None,
                client_labels=None,
                client_env=None,
                **self.params(),
            ),
            "PUBLISH",
        )

    def test_one_present_fails_partial_publication(self):
        self.assertEqual(
            PUBLICATION.classify_publication(
                server_present=True,
                client_present=False,
                server_labels={},
                client_labels=None,
                client_env=None,
                **self.params(),
            ),
            "FAIL_PARTIAL_PUBLICATION",
        )

    def test_exact_existing_pair_is_already_published(self):
        self.assertEqual(
            PUBLICATION.classify_publication(
                server_present=True,
                client_present=True,
                server_labels=server_config()["Labels"],
                client_labels=client_config()["Labels"],
                client_env=client_config()["Env"],
                **self.params(),
            ),
            "ALREADY_PUBLISHED",
        )

    def test_existing_pair_with_wrong_provenance_fails_closed(self):
        labels = server_config()["Labels"]
        labels["org.opencontainers.image.revision"] = "d" * 40
        self.assertEqual(
            PUBLICATION.classify_publication(
                server_present=True,
                client_present=True,
                server_labels=labels,
                client_labels=client_config()["Labels"],
                client_env=client_config()["Env"],
                **self.params(),
            ),
            "FAIL_IMMUTABILITY_VIOLATION",
        )

    def test_client_runtime_extra_environment_does_not_change_identity(self):
        env = client_config()["Env"] + ["PATH=/usr/bin"]
        self.assertEqual(
            PUBLICATION.classify_publication(
                server_present=True,
                client_present=True,
                server_labels=server_config()["Labels"],
                client_labels=client_config()["Labels"],
                client_env=env,
                **self.params(),
            ),
            "ALREADY_PUBLISHED",
        )


if __name__ == "__main__":
    unittest.main()
