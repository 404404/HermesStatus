#!/usr/bin/env python3
"""Decide whether an immutable candidate may be published.

Existing candidate tags are inspected, never overwritten. The caller supplies
only Docker metadata; this module never contacts a registry or prints it.
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any


PUBLICATION_STATES = {
    "PUBLISH",
    "ALREADY_PUBLISHED",
    "FAIL_PARTIAL_PUBLICATION",
    "FAIL_IMMUTABILITY_VIOLATION",
}
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
CATALOG_SHA_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def validate_candidate_tag(candidate_tag: str, revision: str) -> None:
    if not SHA_PATTERN.fullmatch(revision):
        raise ValueError("candidate revision must be a full lowercase Git SHA")
    if candidate_tag != "2.7-" + revision[:12]:
        raise ValueError("candidate tag does not match the full source revision")


def _label_matches(labels: dict[str, Any], expected: dict[str, str]) -> bool:
    return all(labels.get(key) == value for key, value in expected.items())


def _base_provenance(labels: dict[str, Any], *, version: str, revision: str, component: str) -> bool:
    if not SHA_PATTERN.fullmatch(revision):
        return False
    return _label_matches(
        labels,
        {
            "org.opencontainers.image.version": version,
            "org.opencontainers.image.revision": revision,
            "io.hermesstatus.component": component,
        },
    )


def _env_values(env: list[Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in env:
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            result[key] = value
    return result


def published_candidate_is_valid(
    *,
    server_labels: dict[str, Any],
    client_labels: dict[str, Any],
    client_env: list[Any],
    version: str,
    revision: str,
    catalog_revision: str,
    catalog_schema_version: int,
    catalog_sha256: str,
) -> bool:
    if not _base_provenance(server_labels, version=version, revision=revision, component="server"):
        return False
    if not _base_provenance(client_labels, version=version, revision=revision, component="client"):
        return False
    if not SHA_PATTERN.fullmatch(catalog_revision):
        return False
    if catalog_schema_version != 1 or not CATALOG_SHA_PATTERN.fullmatch(catalog_sha256):
        return False
    if not _label_matches(
        client_labels,
        {
            "io.hermesstatus.unifi.catalog.revision": catalog_revision,
            "io.hermesstatus.unifi.catalog.schema_version": str(catalog_schema_version),
            "io.hermesstatus.unifi.catalog.sha256": catalog_sha256,
        },
    ):
        return False
    values = _env_values(client_env)
    expected = {
        "HERMESSTATUS_CLIENT_VERSION": version,
        "HERMESSTATUS_CLIENT_REVISION": revision,
        "HERMESSTATUS_UNIFI_CATALOG_REVISION": catalog_revision,
        "HERMESSTATUS_UNIFI_CATALOG_SCHEMA_VERSION": str(catalog_schema_version),
        "HERMESSTATUS_UNIFI_CATALOG_SHA256": catalog_sha256,
    }
    return all(values.get(key) == value for key, value in expected.items())


def classify_publication(
    *,
    server_present: bool,
    client_present: bool,
    server_labels: dict[str, Any] | None,
    client_labels: dict[str, Any] | None,
    client_env: list[Any] | None,
    version: str,
    revision: str,
    catalog_revision: str,
    catalog_schema_version: int,
    catalog_sha256: str,
) -> str:
    if not SHA_PATTERN.fullmatch(revision) or not SHA_PATTERN.fullmatch(catalog_revision):
        return "FAIL_IMMUTABILITY_VIOLATION"
    if catalog_schema_version != 1 or not CATALOG_SHA_PATTERN.fullmatch(catalog_sha256):
        return "FAIL_IMMUTABILITY_VIOLATION"
    if not server_present and not client_present:
        return "PUBLISH"
    if server_present != client_present:
        return "FAIL_PARTIAL_PUBLICATION"
    if published_candidate_is_valid(
        server_labels=server_labels or {},
        client_labels=client_labels or {},
        client_env=client_env or [],
        version=version,
        revision=revision,
        catalog_revision=catalog_revision,
        catalog_schema_version=catalog_schema_version,
        catalog_sha256=catalog_sha256,
    ):
        return "ALREADY_PUBLISHED"
    return "FAIL_IMMUTABILITY_VIOLATION"


def _json_argument(value: str, label: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-present", action="store_true")
    parser.add_argument("--client-present", action="store_true")
    parser.add_argument("--server-labels", default="{}")
    parser.add_argument("--client-labels", default="{}")
    parser.add_argument("--client-env", default="[]")
    parser.add_argument("--candidate-tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--catalog-revision", required=True)
    parser.add_argument("--catalog-schema-version", type=int, required=True)
    parser.add_argument("--catalog-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_candidate_tag(args.candidate_tag, args.revision)
        server_labels = _json_argument(args.server_labels, "server labels")
        client_labels = _json_argument(args.client_labels, "client labels")
        client_env = _json_argument(args.client_env, "client environment")
        if not isinstance(server_labels, dict) or not isinstance(client_labels, dict) or not isinstance(client_env, list):
            raise ValueError("candidate metadata has invalid shape")
        state = classify_publication(
            server_present=args.server_present,
            client_present=args.client_present,
            server_labels=server_labels,
            client_labels=client_labels,
            client_env=client_env,
            version=args.version,
            revision=args.revision,
            catalog_revision=args.catalog_revision,
            catalog_schema_version=args.catalog_schema_version,
            catalog_sha256=args.catalog_sha256,
        )
    except ValueError as exc:
        print(f"CANDIDATE_PUBLICATION=FAIL: {exc}")
        return 1
    print(f"CANDIDATE_PUBLICATION={state}")
    return 0 if state in {"PUBLISH", "ALREADY_PUBLISHED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
