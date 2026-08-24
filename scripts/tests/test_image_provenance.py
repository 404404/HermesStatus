import copy
import importlib.util
import pathlib
import unittest


SCRIPT = pathlib.Path(__file__).parents[1] / "validate_image_provenance.py"
SPEC = importlib.util.spec_from_file_location("validate_image_provenance", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


REVISION = "a" * 40
CREATED = "2026-07-21T00:00:00Z"
SOURCE = "https://github.com/404404/HermesStatus"


def valid_inspect():
    return {
        "Id": "sha256:" + "b" * 64,
        "Config": {
            "Entrypoint": ["/usr/local/bin/serverstatus"],
            "Labels": {
                "org.opencontainers.image.title": "HermesStatus Server",
                "org.opencontainers.image.description": "read-only dashboard",
                "org.opencontainers.image.version": "2.0-test",
                "org.opencontainers.image.revision": REVISION,
                "org.opencontainers.image.created": CREATED,
                "org.opencontainers.image.source": SOURCE,
                "org.opencontainers.image.licenses": "MIT",
            },
        },
    }


def validate(payload):
    return MODULE.validate_inspect(
        payload,
        expected_title="HermesStatus Server",
        expected_entrypoint=["/usr/local/bin/serverstatus"],
        version="2.0-test",
        revision=payload["Config"]["Labels"]["org.opencontainers.image.revision"],
        created=payload["Config"]["Labels"]["org.opencontainers.image.created"],
        source=SOURCE,
    )


class ImageProvenanceTests(unittest.TestCase):
    def test_publisher_preserves_component_metadata(self):
        workflow = (
            pathlib.Path(__file__).resolve().parents[2]
            / ".github/workflows/publish-2.3-candidate-images.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("name: Publish 2.3 Candidate Images", workflow)
        self.assertIn('PRODUCT_VERSION: "2.3"', workflow)
        self.assertIn('echo "version=${PRODUCT_VERSION}-${GITHUB_SHA::12}"', workflow)
        self.assertNotIn("2.3-preview", workflow)
        self.assertIn("org.opencontainers.image.title=HermesStatus Server", workflow)
        self.assertIn("org.opencontainers.image.title=HermesStatus Client", workflow)
        self.assertIn("io.hermesstatus.component=server", workflow)
        self.assertIn("io.hermesstatus.component=client", workflow)
        for label in (
            "org.opencontainers.image.version=${{ steps.provenance.outputs.version }}",
            "org.opencontainers.image.revision=${{ github.sha }}",
            "org.opencontainers.image.created=${{ steps.provenance.outputs.build_date }}",
            "org.opencontainers.image.source=${{ env.IMAGE_SOURCE }}",
            "org.opencontainers.image.licenses=MIT",
        ):
            self.assertEqual(workflow.count(label), 2)

    def test_server_dockerfile_copies_multi_device_contract_package(self):
        dockerfile = (
            pathlib.Path(__file__).resolve().parents[2] / "Dockerfile.server"
        ).read_text(encoding="utf-8")
        self.assertIn("COPY server/contracts ./contracts", dockerfile)

    def test_client_dockerfile_sets_client_component_metadata(self):
        dockerfile = (
            pathlib.Path(__file__).resolve().parents[2] / "Dockerfile.client"
        ).read_text(encoding="utf-8")
        self.assertIn('io.hermesstatus.component="client"', dockerfile)

    def test_server_dockerfile_sets_server_component_metadata(self):
        dockerfile = (
            pathlib.Path(__file__).resolve().parents[2] / "Dockerfile.server"
        ).read_text(encoding="utf-8")
        self.assertIn('io.hermesstatus.component="server"', dockerfile)

    def test_valid_metadata(self):
        result = validate(valid_inspect())
        self.assertEqual(result["revision"], REVISION)

    def test_short_revision_is_rejected(self):
        payload = valid_inspect()
        payload["Config"]["Labels"]["org.opencontainers.image.revision"] = "abc123"
        with self.assertRaises(MODULE.ValidationError):
            validate(payload)

    def test_non_utc_created_is_rejected(self):
        payload = valid_inspect()
        payload["Config"]["Labels"]["org.opencontainers.image.created"] = "2026-07-21T08:00:00+08:00"
        with self.assertRaises(MODULE.ValidationError):
            validate(payload)

    def test_changed_entrypoint_is_rejected(self):
        payload = valid_inspect()
        payload["Config"]["Entrypoint"] = ["/bin/sh"]
        with self.assertRaises(MODULE.ValidationError):
            validate(payload)

    def test_secret_like_label_is_rejected(self):
        payload = copy.deepcopy(valid_inspect())
        payload["Config"]["Labels"]["example.password"] = "should-not-exist"
        with self.assertRaises(MODULE.ValidationError):
            validate(payload)


if __name__ == "__main__":
    unittest.main()
