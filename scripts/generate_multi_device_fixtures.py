#!/usr/bin/env python3
"""Generate deterministic, entirely synthetic Stage A fixtures."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VALID = ROOT / "testdata" / "multi_device" / "valid"
INVALID = ROOT / "testdata" / "multi_device" / "invalid"
SYNTHETIC_NOW = "2026-07-01T12:00:00Z"
FUTURE = "2099-01-01T00:00:00Z"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
MAX_REGISTERED_DEVICES = 16


def write(directory: Path, name: str, value: Any) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def ownership(mode: str, active: str | None, expiry: str | None) -> dict[str, Any]:
    return {
        "mode": mode,
        "active_protocol": active,
        "cutover_not_after": expiry,
    }


def device(
    identifier: str,
    order: int,
    *,
    enabled: bool = True,
    mode: str = "device_v2",
    active: str = "device_v2",
    expiry: str | None = None,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "display_name": f"Synthetic {identifier}",
        "expected_fqdn": f"{identifier}.example.invalid",
        "enabled": enabled,
        "order": order,
        "tags": ["synthetic"],
        "group": "fixture",
        "ingestion": ownership(mode, active, expiry),
    }


def registry(devices: list[dict[str, Any]], default: str | None = None) -> dict[str, Any]:
    return {
        "version": 1,
        "defaults": {
            "default_device_id": default or devices[0]["id"],
            "stale_seconds": 900,
            "offline_seconds": 1800,
        },
        "devices": devices,
    }


def stats_server(
    extension: dict[str, Any],
    identifier: str,
    order: int,
    status: str,
    identity: str,
    protocol: str,
) -> dict[str, Any]:
    value = copy.deepcopy(extension)
    stale = status in {"stale", "offline", "never_seen", "disabled", "identity_error"}
    seen = None if status == "never_seen" else SYNTHETIC_NOW
    value.update(
        {
            "device_id": identifier,
            "display_name": f"Synthetic {identifier}",
            "status": status,
            "identity_status": identity,
            "protocol_mode": protocol,
            "last_seen": seen,
            "collected_at": seen,
            "stale": stale,
            "expected_fqdn": None,
            "reported_fqdn": None,
            "name": f"Synthetic {identifier}",
            "type": "synthetic",
            "host": f"{identifier}.example.invalid",
            "location": "fixture",
            "online4": status == "online",
            "online6": False,
            "_fixture_order": order,
        }
    )
    value.pop("_fixture_order")
    return value


def envelope_base() -> dict[str, Any]:
    return json.loads((VALID / "envelope-all-domains.json").read_text(encoding="utf-8"))


def generate_valid() -> None:
    extension = json.loads(
        (ROOT / "testdata" / "migration" / "stats-empty.json").read_text(encoding="utf-8")
    )
    single = {
        "schema_version": 2,
        "generated_at": SYNTHETIC_NOW,
        "default_device_id": "device-alpha",
        "servers": [
            stats_server(extension, "device-alpha", 10, "online", "matched", "device_v2")
        ],
        "sslcerts": [],
        "updated": "1782907200",
    }
    write(VALID, "stats-v2-single.json", single)

    four_specs = [
        ("device-beta", 10, "never_seen", "unknown", "none"),
        ("device-gamma", 10, "stale", "matched", "device_v2"),
        ("device-alpha", 20, "offline", "matched", "legacy_single_device"),
        ("device-delta", 30, "disabled", "disabled", "none"),
    ]
    four = {
        "schema_version": 2,
        "generated_at": SYNTHETIC_NOW,
        "default_device_id": "device-beta",
        "servers": [
            stats_server(extension, identifier, order, status, identity, protocol)
            for identifier, order, status, identity, protocol in four_specs
        ],
        "sslcerts": [],
        "updated": "1782907200",
    }
    write(VALID, "stats-v2-four.json", four)
    write(
        VALID,
        "stats-never-seen.json",
        {**single, "servers": [four["servers"][0]], "default_device_id": "device-beta"},
    )
    write(
        VALID,
        "stats-stale-offline.json",
        {**single, "servers": four["servers"][1:3], "default_device_id": "device-gamma"},
    )
    write(
        VALID,
        "stats-disabled.json",
        {**single, "servers": [four["servers"][3]], "default_device_id": "device-delta"},
    )

    tie = registry([device("device-zeta", 10), device("device-alpha", 10)], "device-alpha")
    write(VALID, "registry-order-tie.json", tie)
    write(
        VALID,
        "registry-16.json",
        registry(
            [
                device(f"synthetic-{index:03d}", index)
                for index in range(MAX_REGISTERED_DEVICES)
            ]
        ),
    )
    sixteen = {
        **single,
        "servers": [
            stats_server(
                extension,
                f"synthetic-{index:03d}",
                index,
                "online",
                "matched",
                "device_v2",
            )
            for index in range(MAX_REGISTERED_DEVICES)
        ],
        "default_device_id": "synthetic-000",
    }
    write(VALID, "stats-v2-sixteen.json", sixteen)
    write(
        VALID,
        "response-success.json",
        {
            "accepted": True,
            "server_time": SYNTHETIC_NOW,
            "config_generation": "synthetic-generation",
            "monitors": [],
        },
    )
    write(
        VALID,
        "response-error.json",
        {"error": {"code": "invalid_request", "request_id": "synthetic-request-id"}},
    )

    domains = {
        name: copy.deepcopy(extension[name])
        for name in ("hardware", "docker", "hermes", "lucky")
    }
    persistence = {
        "version": 2,
        "generated_at": SYNTHETIC_NOW,
        "devices": [
            {
                "device_id": "device-alpha",
                "last_accepted_generation": 7,
                "last_seen": SYNTHETIC_NOW,
                "collected_at": SYNTHETIC_NOW,
                "protocol_mode": "device_v2",
                "status_at_snapshot": "online",
                "runtime_observations": {
                    "os": "Synthetic OS",
                    "cpu_model": "Synthetic CPU",
                },
                "domains": domains,
            }
        ],
        "orphaned_devices": [
            {
                "orphan_id": "removed-device-001",
                "device_id": "device-removed",
                "reason": "removed_device",
                "source_version": 2,
                "snapshot": {"status_at_snapshot": "offline"},
            }
        ],
    }
    write(VALID, "persistence-v2.json", persistence)
    migration_source = {
        "servers": [
            {
                "name": "Synthetic Legacy A",
                "type": "synthetic",
                "host": "legacy-a.example.invalid",
                "location": "fixture",
            },
            {
                "name": "Synthetic Unmatched",
                "type": "synthetic",
                "host": "unmatched.example.invalid",
                "location": "fixture",
            },
        ]
    }
    write(
        VALID,
        "persistence-migration-v1-v2.json",
        {
            "source": migration_source,
            "bindings": [
                {
                    "source": copy.deepcopy(migration_source["servers"][0]),
                    "device_id": "device-alpha",
                }
            ],
            "expected": {
                "version": 2,
                "device_ids": ["device-alpha"],
                "restored_status": "offline",
                "freshness_reset": True,
            },
        },
    )
    v1_single = {
        "servers": [
            {
                "name": "Synthetic Legacy A",
                "type": "synthetic",
                "host": "legacy-a.example.invalid",
                "location": "fixture",
            }
        ]
    }
    v1_four = {
        "servers": [
            {
                "name": f"Synthetic Legacy {index}",
                "type": "synthetic",
                "host": f"legacy-{index}.example.invalid",
                "location": "fixture",
            }
            for index in range(4)
        ]
    }
    write(VALID, "persistence-v1-single.json", v1_single)
    write(VALID, "persistence-v1-four.json", v1_four)
    write(
        VALID,
        "persistence-v1-sixteen.json",
        {
            "servers": [
                {
                    "name": f"Synthetic Legacy {index:02d}",
                    "type": "synthetic",
                    "host": f"legacy-{index:02d}.example.invalid",
                    "location": "fixture",
                }
                for index in range(MAX_REGISTERED_DEVICES)
            ]
        },
    )
    write(
        VALID,
        "persistence-migration-unmatched.json",
        {"source": v1_single, "bindings": [], "expected_orphan_count": 1},
    )
    write(
        VALID,
        "persistence-migration-removed.json",
        {
            "source": v1_single,
            "bindings": [
                {"source": copy.deepcopy(v1_single["servers"][0]), "device_id": "device-removed"}
            ],
            "expected_reason": "removed_device",
        },
    )
    write(
        VALID,
        "persistence-migration-readded.json",
        {
            "source": v1_single,
            "bindings": [
                {"source": copy.deepcopy(v1_single["servers"][0]), "device_id": "device-alpha"}
            ],
            "registry_fixture": "registry-single.json",
            "expected_status": "offline",
        },
    )
    write(
        VALID,
        "persistence-migration-disabled.json",
        {
            "source": v1_single,
            "bindings": [
                {"source": copy.deepcopy(v1_single["servers"][0]), "device_id": "device-delta"}
            ],
            "registry_fixture": "registry-four.json",
            "expected_status": "disabled",
        },
    )


def invalid_registry_cases() -> dict[str, Any]:
    base = registry([device("device-alpha", 10)])
    cases: dict[str, Any] = {}

    value = copy.deepcopy(base)
    value["devices"].append(copy.deepcopy(value["devices"][0]))
    cases["registry-duplicate-device-id.json"] = value

    value = copy.deepcopy(base)
    value["devices"][0]["id"] = "INVALID ID"
    value["defaults"]["default_device_id"] = "INVALID ID"
    cases["registry-invalid-device-id.json"] = value

    value = copy.deepcopy(base)
    value["defaults"]["default_device_id"] = "missing-device"
    cases["registry-bad-default.json"] = value

    value = copy.deepcopy(base)
    value["devices"][0]["enabled"] = False
    cases["registry-default-disabled.json"] = value

    for name, fqdn in (
        ("registry-bad-fqdn.json", "not_a_fqdn"),
        ("registry-ip-as-fqdn.json", "192.0.2.10"),
        ("registry-url-as-fqdn.json", "https://alpha.example.invalid"),
    ):
        value = copy.deepcopy(base)
        value["devices"][0]["expected_fqdn"] = fqdn
        cases[name] = value

    value = copy.deepcopy(base)
    value["devices"][0]["unexpected"] = True
    cases["registry-unknown-field.json"] = value

    cases["registry-17-devices.json"] = registry(
        [
            device(f"synthetic-{index:03d}", index)
            for index in range(MAX_REGISTERED_DEVICES + 1)
        ]
    )

    value = copy.deepcopy(base)
    value["defaults"]["offline_seconds"] = 900
    cases["registry-invalid-stale-offline.json"] = value

    value = copy.deepcopy(base)
    del value["devices"][0]["ingestion"]
    cases["registry-missing-ingestion.json"] = value

    value = copy.deepcopy(base)
    value["devices"][0]["ingestion"]["mode"] = "both"
    cases["registry-invalid-ingestion-mode.json"] = value

    value = copy.deepcopy(base)
    value["devices"][0]["ingestion"] = ownership("cutover", None, FUTURE)
    cases["registry-cutover-without-active.json"] = value

    value = copy.deepcopy(base)
    value["devices"][0]["ingestion"] = ownership("cutover", "device_v2", None)
    cases["registry-cutover-without-expiry.json"] = value

    value = copy.deepcopy(base)
    value["devices"][0]["ingestion"] = ownership(
        "cutover", "device_v2", "2020-01-01T00:00:00Z"
    )
    cases["registry-expired-cutover.json"] = value
    return cases


def generate_invalid() -> None:
    for name, value in invalid_registry_cases().items():
        write(INVALID, name, value)

    write(
        INVALID,
        "legacy-duplicate-username.json",
        {
            "version": 1,
            "mappings": [
                {"username": "synthetic-user", "device_id": "device-alpha"},
                {"username": "synthetic-user", "device_id": "device-beta"},
            ],
        },
    )
    write(
        INVALID,
        "legacy-duplicate-device.json",
        {
            "version": 1,
            "mappings": [
                {"username": "synthetic-user-a", "device_id": "device-alpha"},
                {"username": "synthetic-user-b", "device_id": "device-alpha"},
            ],
        },
    )

    credential = {
        "version": 1,
        "device_id": "device-alpha",
        "algorithm": "sha256",
        "credentials": [
            {
                "id": "current",
                "digest": DIGEST_A,
                "not_before": "2026-01-01T00:00:00Z",
                "not_after": FUTURE,
            }
        ],
    }
    duplicate = copy.deepcopy(credential)
    duplicate["credentials"].append(copy.deepcopy(duplicate["credentials"][0]))
    write(INVALID, "credential-duplicate-slot.json", duplicate)
    bad_digest = copy.deepcopy(credential)
    bad_digest["credentials"][0]["digest"] = "not-a-synthetic-digest"
    write(INVALID, "credential-invalid-digest.json", bad_digest)
    excessive = copy.deepcopy(credential)
    excessive["credentials"] = [
        {
            "id": "current",
            "digest": DIGEST_A,
            "not_before": "2026-01-01T00:00:00Z",
            "not_after": FUTURE,
        },
        {
            "id": "next",
            "digest": DIGEST_B,
            "not_before": "2026-02-01T00:00:00Z",
            "not_after": FUTURE,
        },
        {
            "id": "next",
            "digest": "c" * 64,
            "not_before": "2026-03-01T00:00:00Z",
            "not_after": FUTURE,
        },
    ]
    write(INVALID, "credential-excessive-count.json", excessive)

    envelope = envelope_base()
    write(
        INVALID,
        "envelope-header-body-mismatch.json",
        {"header_device_id": "device-beta", "body": envelope},
    )
    value = copy.deepcopy(envelope)
    value["unexpected"] = True
    write(INVALID, "envelope-unknown-field.json", value)
    for name, field in (
        ("envelope-credential-in-body.json", "token"),
        ("envelope-config-in-body.json", "config"),
        ("envelope-command-in-body.json", "command"),
    ):
        value = copy.deepcopy(envelope)
        value["stats"][field] = "synthetic-forbidden-value"
        write(INVALID, name, value)
    value = copy.deepcopy(envelope)
    value["collected_at"] = "2026-07-01 12:00:00"
    write(INVALID, "envelope-invalid-collected-at.json", value)
    write(
        INVALID,
        "envelope-oversized-descriptor.json",
        {
            "base_fixture": "envelope-all-domains.json",
            "repeat_field": "custom",
            "synthetic_size_bytes": 1048577,
        },
    )

    write(
        INVALID,
        "persistence-ambiguous-mapping.json",
        {
            "source": {"servers": [{"name": "Synthetic A"}, {"name": "Synthetic B"}]},
            "bindings": [
                {"source": {"name": "Synthetic A"}, "device_id": "device-alpha"},
                {"source": {"name": "Synthetic B"}, "device_id": "device-alpha"},
            ],
        },
    )
    write(
        INVALID,
        "persistence-corrupt-version.json",
        {
            "version": 99,
            "generated_at": SYNTHETIC_NOW,
            "devices": [],
            "orphaned_devices": [],
        },
    )


def main() -> int:
    generate_valid()
    generate_invalid()
    print("generated deterministic multi-device fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
