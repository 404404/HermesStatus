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
PRODUCT_VERSION = "2.5"
CANDIDATE_TAG = "2.5-" + REVISION[:12]


def valid_inspect():
    return {
        "Id": "sha256:" + "b" * 64,
        "Config": {
            "Entrypoint": ["/usr/local/bin/serverstatus"],
            "Labels": {
                "org.opencontainers.image.title": "HermesStatus Server",
                "org.opencontainers.image.description": "read-only dashboard",
                "org.opencontainers.image.version": PRODUCT_VERSION,
                "org.opencontainers.image.revision": REVISION,
                "org.opencontainers.image.created": CREATED,
                "org.opencontainers.image.source": SOURCE,
                "org.opencontainers.image.licenses": "MIT",
                "io.hermesstatus.component": "server",
            },
            "Env": [
                "HERMESSTATUS_CLIENT_VERSION=" + PRODUCT_VERSION,
                "HERMESSTATUS_CLIENT_REVISION=" + REVISION,
                "HERMESSTATUS_CLIENT_BUILD_TIME=" + CREATED,
            ],
        },
    }


def validate(payload):
    return MODULE.validate_inspect(
        payload,
        expected_title="HermesStatus Server",
        expected_entrypoint=["/usr/local/bin/serverstatus"],
        version=PRODUCT_VERSION,
        revision=payload["Config"]["Labels"]["org.opencontainers.image.revision"],
        created=payload["Config"]["Labels"]["org.opencontainers.image.created"],
        source=SOURCE,
    )


class ImageProvenanceTests(unittest.TestCase):
    def test_publisher_preserves_component_metadata(self):
        workflow = (
            pathlib.Path(__file__).resolve().parents[2]
            / ".github/workflows/publish-2.5-candidate-images.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("name: Publish 2.5 Candidate Images", workflow)
        self.assertIn('PRODUCT_VERSION: "2.5"', workflow)
        self.assertIn('echo "candidate_tag=${PRODUCT_VERSION}-${GITHUB_SHA::12}"', workflow)
        self.assertIn('echo "product_version=${PRODUCT_VERSION}"', workflow)
        self.assertNotIn("2.3-preview", workflow)
        self.assertIn("org.opencontainers.image.title=HermesStatus Server", workflow)
        self.assertIn("org.opencontainers.image.title=HermesStatus Client", workflow)
        self.assertIn("io.hermesstatus.component=server", workflow)
        self.assertIn("io.hermesstatus.component=client", workflow)
        for label in (
            "org.opencontainers.image.version=${{ steps.provenance.outputs.product_version }}",
            "org.opencontainers.image.revision=${{ github.sha }}",
            "org.opencontainers.image.created=${{ steps.provenance.outputs.build_date }}",
            "org.opencontainers.image.source=${{ env.IMAGE_SOURCE }}",
            "org.opencontainers.image.licenses=MIT",
        ):
            self.assertEqual(workflow.count(label), 2)

    def test_ci_workflow_separates_candidate_tag_from_product_version(self):
        workflow = (
            pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('echo "candidate_tag=2.5-${GITHUB_SHA::12}"', workflow)
        self.assertIn('echo "product_version=2.5"', workflow)
        self.assertIn("VERSION=${{ steps.provenance.outputs.product_version }}", workflow)
        self.assertIn("hermesstatus-server:${{ steps.provenance.outputs.candidate_tag }}", workflow)
        self.assertIn("hermesstatus-client:${{ steps.provenance.outputs.candidate_tag }}", workflow)

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

    def test_candidate_tag_is_distinct_from_formal_product_version(self):
        MODULE.validate_candidate_tag(CANDIDATE_TAG, PRODUCT_VERSION, REVISION)
        with self.assertRaises(MODULE.ValidationError):
            MODULE.validate_candidate_tag(CANDIDATE_TAG, CANDIDATE_TAG, REVISION)

    def test_candidate_tag_must_match_full_revision_prefix(self):
        with self.assertRaises(MODULE.ValidationError):
            MODULE.validate_candidate_tag("2.5-bbbbbbbbbbbb", PRODUCT_VERSION, REVISION)

    def test_oci_version_rejects_candidate_tag(self):
        payload = valid_inspect()
        payload["Config"]["Labels"]["org.opencontainers.image.version"] = CANDIDATE_TAG
        with self.assertRaises(MODULE.ValidationError):
            validate(payload)

    def test_client_runtime_values_must_match_provenance(self):
        MODULE.validate_client_runtime(
            valid_inspect()["Config"],
            version=PRODUCT_VERSION,
            revision=REVISION,
            created=CREATED,
        )
        payload = valid_inspect()
        payload["Config"]["Env"][0] = "HERMESSTATUS_CLIENT_VERSION=" + CANDIDATE_TAG
        with self.assertRaises(MODULE.ValidationError):
            MODULE.validate_client_runtime(
                payload["Config"],
                version=PRODUCT_VERSION,
                revision=REVISION,
                created=CREATED,
            )

    def test_server_runtime_values_must_use_formal_product_version(self):
        values = MODULE.parse_server_version(
            "serverstatus 2.5 commit=" + REVISION + " built=" + CREATED + "\n"
        )
        MODULE.validate_server_runtime_values(
            values, version=PRODUCT_VERSION, revision=REVISION, created=CREATED
        )
        values["version"] = CANDIDATE_TAG
        with self.assertRaises(MODULE.ValidationError):
            MODULE.validate_server_runtime_values(
                values, version=PRODUCT_VERSION, revision=REVISION, created=CREATED
            )

    def test_component_role_mismatch_is_rejected(self):
        with self.assertRaises(MODULE.ValidationError):
            MODULE.validate_component(valid_inspect()["Config"], "client")

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
