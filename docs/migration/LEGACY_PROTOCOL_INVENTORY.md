# Legacy extension protocol inventory

## Contents

- [Scope](#scope)
- [Wire fields](#wire-fields)
- [Decode path](#decode-path)
- [State and output boundary](#state-and-output-boundary)
- [Current producers](#current-producers)
- [Failure behavior](#failure-behavior)
- [Test evidence](#test-evidence)
- [Removal conditions](#removal-conditions)
- [Risks and open items](#risks-and-open-items)

## Scope

This inventory records the transitional input compatibility for `hardware_json`, `docker_json`, and `hermes_json`. It is a static code audit only: no parser, wire protocol, Schema, payload, logging, telemetry, or Server behavior was changed.

The authoritative implementation is the current Go code on `2.0`. Some earlier migration documents describe the pre-B2 state in which Go ignored these fields; those statements are historical gap evidence, not the current implementation.

## Wire fields

| Field | Go representation | JSON tag | Decoded limit | Required | Null behavior | Version behavior |
| --- | --- | --- | ---: | --- | --- | --- |
| `hardware_json` | `legacyExtensionWire.HardwareJSON string` | `hardware_json,omitempty` | 4 KiB | No | `null` becomes an invalid empty legacy payload and degrades only hardware | Accepted without `extension_version`; structured `hardware` takes precedence |
| `docker_json` | `legacyExtensionWire.DockerJSON string` | `docker_json,omitempty` | 32 KiB | No | `null` becomes an invalid empty legacy payload and degrades only Docker | Accepted without `extension_version`; structured `docker` takes precedence |
| `hermes_json` | `legacyExtensionWire.HermesJSON string` | `hermes_json,omitempty` | 32 KiB | No | `null` becomes an invalid empty legacy payload and degrades only Hermes | Accepted without `extension_version`; structured `hermes` takes precedence |

The constants are defined in `server/extension_model.go`. The complete TCP update is limited to 1 MiB by `maxRequestBody` in `server/model.go` and by the scanner in `server/tcp_server.go`.

`legacyExtensionWire` documents the transition shape and is exercised by model tests, but production decoding uses a `map[string]json.RawMessage` in `decodeAgentUpdate`. This avoids embedding legacy strings in `AgentStats`, `NodeState`, or normal stats types.

Structured extensions require the exact `extension_version` value `1.0-draft`, with a maximum length of 32 characters. Legacy-only input does not require that field. If both forms for one domain are present, the structured form wins even when the legacy value is otherwise valid.

## Decode path

```text
TCP update line
  -> 1 MiB line and payload limit
  -> native AgentStats decode
  -> raw top-level field map
  -> structured/legacy field precedence per domain
  -> outer legacy JSON string decode
  -> decoded-byte limit and JSON-object requirement
  -> DecodeHardwareStatsJSON / DecodeDockerStatsJSON / DecodeHermesStatsJSON
  -> shared strict domain validation and sanitization
  -> ExtensionStats
  -> NodeState.Extension as ExtensionSnapshot
  -> snapshot freshness calculation
  -> /json/stats.json structured hardware/docker/hermes objects
```

The relevant production locations are:

| Stage | File and symbol |
| --- | --- |
| TCP line handling | `server/tcp_server.go`: scanner and `decodeAgentUpdate` call |
| Precedence and legacy decode | `server/extension_pipeline.go`: `decodeAgentUpdate`, `decodeWireDomain`, `decodeDomainPayload` |
| Type and limits | `server/extension_model.go`: `legacyExtensionWire`, `MaxLegacy*JSONBytes` |
| Domain validation | `server/extension_validation.go`: `Decode*StatsJSON`, `Validate*` |
| Node storage | `server/app.go`: `NodeState.Extension`, `updateAgent` |
| Snapshot output | `server/app.go`: `snapshotStats`; `server/extension_pipeline.go`: `snapshotExtension` |
| HTTP output | `server/http_server.go`: `/json/stats.json` |

## State and output boundary

Legacy input is normalized into `HardwareStats`, `DockerStats`, and `HermesStats` before storage. The raw strings are not fields on `NodeState` or `ExtensionSnapshot` and are not persisted as raw input.

Decode issue logging is limited to username, domain, error code, and payload length. It does not log the payload. Snapshot and OpenAPI output expose only the structured allowlist. The browser cannot receive the three legacy field names through `/json/stats.json`.

Persisted stats may contain the validated structured extension, but startup recovery restores only native traffic baselines and selected native identity fields. It does not restore legacy input or mark persisted extension data as fresh.

## Current producers

`clients/host_collector.py` constructs `extension_version`, `hardware`, `docker`, and `hermes` directly. `clients/test_host_collector.py` asserts that generated payloads contain no key ending in `_json` and validates the structured payload against the migration Schema.

The repository therefore has no current tracked producer of the three legacy JSON-string fields. This static result does not prove that every external or previously deployed client has been upgraded; the Server has no legacy-usage telemetry, and this task did not inspect a deployment environment.

## Failure behavior

| Condition | Result |
| --- | --- |
| Legacy field absent and no structured domain | Stable `not_reported` object |
| Structured and legacy field both present | Structured field is used; matching legacy field is ignored |
| Outer value is not a JSON string | Domain degrades with `invalid_json` |
| Decoded string is empty, `null`, or not a JSON object | Domain degrades with `invalid_json` |
| Decoded legacy content exceeds its domain limit | Domain degrades with `payload_too_large` |
| Domain has unknown fields or invalid values | Shared validator degrades or sanitizes that domain |
| One extension domain fails | Native metrics and the other valid extension domains remain accepted |
| Complete update is invalid JSON or exceeds 1 MiB | Existing whole-update failure behavior applies |

Degraded objects use safe error codes and messages. Secret-like values are sanitized before state; rejected unknown content and raw payloads do not survive normalization.

## Test evidence

| Behavior | Test evidence |
| --- | --- |
| Legacy three-domain decode | `server/extension_pipeline_test.go`: `TestDecodeAgentUpdateLegacyDomains` |
| Structured precedence | `TestStructuredDomainTakesPriorityOverLegacy` |
| Stable no-extension defaults | `TestNativeClientGetsStableNotReportedDomains` |
| Version requirement for structured input | `TestStructuredUpdateRequiresSupportedVersion` |
| Overall 1 MiB limit | `TestDecodeAgentUpdateKeepsGlobalSizeLimit` |
| Legacy limit and object requirement | `TestLegacyDomainLimitsAndObjectRequirement` |
| Native/other-domain preservation | `TestInvalidStructuredDomainDoesNotBlockNativeOrOtherDomains` |
| Secret sanitization | `TestExtensionSecretsAreCleanedBeforeState` |
| No raw legacy state | `TestNodeStateContainsOnlyStructuredExtensionState` |
| No legacy HTTP/OpenAPI output | `server/extension_http_test.go` |
| Transition type cannot enter normal serialization | `server/extension_model_test.go` |
| Structured client payload | `clients/test_host_collector.py`: `test_structured_payload_matches_schema_and_contains_no_legacy_or_secret` |

## Removal conditions

Do not remove the compatibility parser as part of repository governance. A future isolated removal PR requires all of the following:

1. An inventory showing that every supported client sends structured fields.
2. A documented compatibility window covering at least the agreed release cycle.
3. An upgrade note for external clients and rollback guidance.
4. Tests proving native clients and structured extension clients remain compatible.
5. Contract and migration-document updates made in the same removal PR.
6. Explicit approval to change the wire compatibility boundary.

Static repository evidence supports eventual removal, but deployment coverage is unknown. The current recommendation is **retain**.

## Risks and open items

- There is no runtime counter proving whether legacy input is still received.
- The compatibility sunset has no confirmed version or date.
- Earlier pre-B2 documents contain now-resolved gap language and should be read as historical snapshots.
- `legacyExtensionWire` is not instantiated by the production decoder; retaining the type is useful for contract visibility and tests but should be reconsidered together with parser removal.

Related material: [stats contract](STATS_CONTRACT.md), [Go implementation map](GO_IMPLEMENTATION_MAP.md), [source decisions](DATA_SOURCE_DECISIONS.md), [legacy candidates](LEGACY.md), and [migration plan](MIGRATION_PLAN.md).
