# HermesStatus 2.2 Multi-Device Architecture

Status: Stage A contract candidate implemented as schemas, synthetic fixtures,
and pure mocks; no runtime activation.

This document defines the 2.2 multi-device architecture. It is intentionally
limited to monitoring. It does not add remote control, automatic registration,
multi-tenancy, RBAC, aggregation dashboards, or secret-management APIs.

## 1. Baseline and audit result

The formal 2.2 base is the latest integrated 2.1 revision:
`868e6f995fa877cd77d2200661445d2bd31c3c0f`. The earlier 2.1 feature merge is
also present in that revision. The current integration branch is `2.0`; there
were no open pull requests when this design audit was performed.

The runtime image inspected during the audit still declared the earlier
revision `733b9dd498e9794ca9414bb9ec20b80116720426`. That runtime is evidence only:
it is not the 2.2 source baseline and this design round does not replace it.

Current behavior:

| Concern | Current 2.1 behavior | 2.2 decision |
| --- | --- | --- |
| Client identity | `username` in the TCP handshake | Canonical `device_id`; `username` is a legacy mapping only |
| Server index | `map[string]*NodeState`, keyed by username | Keep one map and one `NodeState` type; re-key by `device_id` |
| Concurrent clients | Per-node state and connection ID; duplicate same username rejected | Preserve isolation and add race/authorization tests |
| Stats collection | Top-level `servers[]` | Keep `servers[]` and evolve each item minimally |
| UI selection | First enabled server, otherwise first server | Explicit `selectedDeviceId` and a shared selector |
| Ordering | Server configuration order | Registry `order`, then `device_id` |
| Disconnect | Native display state is retained; connection becomes offline | Retain all device state with explicit timestamps/status |
| Restart | Multiple native states restore by mutable display metadata; extensions restart as not fresh | Persist by `device_id`; never make restored data fresh |
| Authentication | Per-username plaintext password over raw TCP | Per-device bearer token, server-side digest, HTTPS |
| State freshness | Extension-domain staleness only | Add device-level recency; retain domain-level staleness |
| Extension isolation | Hardware, Docker, Hermes, and Lucky live in each `NodeState` | Reuse unchanged domain isolation |

The existing implementation therefore already contains useful multi-node
primitives. 2.2 is a normalization and security refactor, not a second
parallel node system.

## 2. Terms and trust boundaries

These values are deliberately distinct:

- **Server URL**: where a Client sends updates.
- **Device ID**: immutable, registry-owned stable key.
- **Device FQDN**: optional identity evidence and metadata, never a key.
- **Display name**: registry-owned UI label.
- **Authentication identity**: the device ID bound to a server-side credential.

The Client may report a hostname, name, and FQDN. Those values are observations,
not authority. A Client cannot change registry order, enabled state, canonical
display name, expected FQDN, freshness thresholds, or credential bindings.

## 3. Canonical data flow

```text
2.2 HTTPS adapter ─┐
                   ├─ authenticate ─ validate identity ─ decode current stats
2.1 TCP adapter ───┘                                      │
                                                          ▼
                                               ingestDeviceUpdate(device_id)
                                                          │
                                              one registry-backed NodeState
                                                          │
                                      persistence snapshot + stats projection
                                                          │
                                         one browser document, local selection
```

Both adapters terminate at the same ingestion method. The current domain
decoders, validation limits, sanitizers, timestamps, and per-domain failure
isolation remain authoritative. The legacy TCP adapter constructs a canonical
internal envelope; it does not maintain a separate legacy state store.

## 4. Server state model

The registry creates a `NodeState` for every registered device, including
`never_seen` and disabled devices. The runtime map is keyed only by
`device_id`. Each state contains:

- registry authority: `id`, `display_name`, `expected_fqdn`, `enabled`,
  `order`, tags/group;
- observations: `reported_fqdn`, `reported_hostname`, `collected_at`;
- server facts: `identity_status`, `status`, `protocol_mode`, `last_seen`;
- current native metrics and the existing Hardware, Docker, Hermes, and Lucky
  domain snapshots;
- legacy connection ID/connection flags where the TCP adapter needs them;
- traffic baselines and persistence metadata.

Updates use this sequence under the existing node locks:

1. authenticate to one `device_id`;
2. require header identity, body identity, registry ID, and credential binding
   to agree;
3. validate FQDN and determine identity status;
4. decode all domains with current isolation semantics;
5. update only that device state using a connection/request generation check;
6. atomically publish/persist the resulting collection.

No request can select another map key after authentication.

## 5. Status semantics

Identity states are:

- `matched`: reported and expected identity evidence agree;
- `fqdn_mismatch`: both exist and differ;
- `missing_fqdn`: the registry expects one but none was reported;
- `unregistered`: rejected request/audit outcome, never an accepted update;
- `disabled`: registered device cannot update;
- `unknown`: no FQDN expectation is configured.

Device states are:

- `online`: recent accepted update with healthy required domains;
- `degraded`: recent update with one or more domain errors/stale domains;
- `stale`: last accepted update exceeds `stale_seconds`;
- `offline`: exceeds `offline_seconds`, or a legacy connection closed and no
  newer accepted update exists;
- `never_seen`: registered but no accepted update or restored state exists;
- `disabled`: registry disables the device;
- `identity_error`: most recent authenticated update had unacceptable identity
  evidence and did not replace metrics.

Precedence is:

`disabled > never_seen > identity_error > offline > stale > degraded > online`.

`last_seen` is server receipt time. `collected_at` is an RFC3339 UTC timestamp
reported by the Client and is bounded against unreasonable clock skew. Device
recency is based on `last_seen`, never solely on the Client clock. Domain-level
staleness remains independent.

## 6. Stats contract direction

The existing `servers[]` collection is retained to minimize 2.1 consumer
breakage. 2.2 adds collection metadata and canonical identity/state fields:

```json
{
  "schema_version": 2,
  "generated_at": "2026-01-01T00:00:00Z",
  "updated": 1767225600,
  "default_device_id": "gk50-hermes",
  "sslcerts": [],
  "servers": [
    {
      "device_id": "gk50-hermes",
      "display_name": "GK50 Hermes",
      "expected_fqdn": null,
      "reported_fqdn": null,
      "identity_status": "matched",
      "status": "online",
      "protocol_mode": "device_v2",
      "enabled": true,
      "last_seen": "2026-01-01T00:00:00Z",
      "collected_at": "2026-01-01T00:00:00Z",
      "stale": false,
      "hardware": {},
      "docker": {},
      "hermes": {},
      "lucky": {}
    }
  ]
}
```

Full FQDN values are `null` in the browser-facing document by default. An
explicit, reviewed server policy may expose them; registry presence alone does
not. Existing `name`, `type`, `host`, `location`, online flags, native metrics,
extension fields, retained compatibility fields, and top-level `sslcerts`
remain during 2.2.

Items are sorted by registry `order`, then `id`. The registry device limit is
128. One projection failure produces a safe degraded item for that device
instead of dropping or corrupting other devices.

## 7. Persistence merge

Persistence version 2 stores runtime observations by `device_id`. On startup:

1. validate the registry;
2. create every registry device;
3. merge persisted runtime fields with the same `device_id`;
4. let registry authority overwrite display, FQDN expectation, enabled, order,
   tags, group, and thresholds;
5. mark all restored devices non-online until a new update is accepted;
6. preserve extension timestamps but never restore them as fresh.

A registry removal does not silently erase persisted history. The entry moves
to an internal `orphaned_devices` section retained for audit/backup and is not
included in normal browser stats. A later restoration of the same ID may
re-associate it after validation.

## 8. Limits and invariants

- `device_id`: `^[a-z0-9][a-z0-9._-]{0,62}$`.
- At most 128 registry devices and 128 emitted devices.
- Request body: at most 1 MiB, including the envelope.
- New structs use strict known-field decoding and bounded strings/arrays.
- Arbitrary metadata, credentials, raw responses, configuration, commands,
  order, enabled, and freshness controls are rejected from Client payloads.
- No device may update another device, even through a body/header mismatch.
- Browser output never contains credential data or server credential mappings.
- Multi-device support adds monitoring endpoints only.

## 9. Expected implementation touch points

Likely new files:

- `server/device_registry.go` and tests;
- `server/device_auth.go` and tests;
- `server/device_protocol.go` and tests;
- `server/device_http.go` and tests;
- a shared Client configuration/transport module and tests;
- UI selector/routing tests and multi-device fixtures.

Likely modified files:

- `server/app.go`, `server/model.go`, `server/tcp_server.go`;
- `server/extension_pipeline.go`, stats persistence code and tests;
- both Client entry points and container configuration examples;
- `webui/src/dashboard.js`, styles, templates, and tests;
- stats contract, operations, security, and provenance documentation.

Exact filenames are implementation-stage choices; the design does not authorize
code changes.

## 10. Implementation phases

1. **Stage A (current candidate):** freeze schemas and fixtures; add registry,
   state, persistence, Client configuration, envelope, projection, generation,
   and ownership contracts behind no runtime activation.
2. Re-key state/persistence by `device_id`; keep the TCP adapter passing tests.
3. Add per-device credentials and the HTTPS adapter feeding the common ingest
   path.
4. Add shared 2.2 Client configuration/transport with fail-soft retry.
5. Evolve stats and add the selector/router without additional fetching.
6. Run compatibility, race, security, persistence, and UI matrices.
7. Perform a separate reviewed deployment phase.

Stage A is implemented only in the uncommitted candidate worktree. Stage B has
not begun. The production runtime still reports the earlier revision
`733b9dd498e9794ca9414bb9ec20b80116720426`; that drift is recorded evidence,
not a development base. Production rollout is blocked until the credential
source, HTTPS termination ownership, FQDN exposure policy, and legacy retirement
window have explicit operational owners.

## 11. Frozen Stage A artifacts

The normative schemas are:

- `schemas/device-registry.schema.json`;
- `schemas/device-credential.schema.json`;
- `schemas/legacy-device-mapping.schema.json`;
- `schemas/client-v2-config.schema.json`;
- `schemas/device-update-v2.schema.json`;
- `schemas/device-update-response-v2.schema.json`;
- `schemas/stats-v2.schema.json`;
- `schemas/persistence-v2.schema.json`.

Pure Go contracts live in `server/contracts` and are not imported by the
production Server. The Python contract module is not imported by either current
Client entrypoint. The frontend addition is fixture/test-only. No HTTPS route,
authentication, NodeState re-key, persistence migration, or selector is active.

## 12. Related documents

- [Device registry](DEVICE_REGISTRY.md)
- [Identity and authentication](DEVICE_IDENTITY_AND_AUTH.md)
- [Protocol and Client configuration](MULTI_DEVICE_PROTOCOL.md)
- [Web UI](MULTI_DEVICE_UI.md)
- [Migration and compatibility](MULTI_DEVICE_MIGRATION.md)
- [Security boundaries](MULTI_DEVICE_SECURITY.md)
- [Deployment and test plan](MULTI_DEVICE_DEPLOYMENT_PLAN.md)
