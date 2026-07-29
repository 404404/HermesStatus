# HermesStatus 2.2 Device Registry

Status: Stage A contract frozen in `schemas/device-registry.schema.json` and
pure validation mocks; not loaded by the production Server.

## 1. Format decision

Use JSON. The Server already uses JSON configuration and Go's standard JSON
decoder. JSON avoids a new parser/dependency and supports strict unknown-field
rejection. The registry is a separate read-only file so monitoring extensions
do not modify the native Server node configuration schema.

Synthetic example:

```json
{
  "version": 1,
  "defaults": {
    "default_device_id": "gk50-hermes",
    "stale_seconds": 900,
    "offline_seconds": 1800
  },
  "devices": [
    {
      "id": "gk50-hermes",
      "display_name": "GK50 Hermes",
      "expected_fqdn": "gk50.example.invalid",
      "enabled": true,
      "order": 10,
      "tags": ["primary"],
      "group": "home",
      "ingestion": {
        "mode": "device_v2",
        "active_protocol": "device_v2",
        "cutover_not_after": null
      }
    },
    {
      "id": "nas-rs820",
      "display_name": "Storage Node",
      "expected_fqdn": "nas.example.invalid",
      "enabled": true,
      "order": 20,
      "tags": ["storage"],
      "group": "home",
      "ingestion": {
        "mode": "legacy",
        "active_protocol": "legacy_single_device",
        "cutover_not_after": null
      }
    }
  ]
}
```

The file is mounted read-only. Reload is either an explicit Server restart or a
fail-closed, atomically validated reload; partial/invalid reloads keep the last
known-good registry and emit only sanitized diagnostics.

## 2. Authority

Registry-owned fields:

- `id`: stable `device_id`;
- `display_name`: canonical browser label;
- `expected_fqdn`: optional normalized DNS identity evidence;
- `enabled`: ingestion permission and UI eligibility;
- `order`: stable presentation order;
- optional `tags` and `group`;
- `default_device_id`, `stale_seconds`, `offline_seconds`.
- `ingestion`: Server-authoritative write ownership; never emitted in stats.

Client observations cannot overwrite these fields. Credentials are stored
separately. The registry must never contain a token, password, cookie, private
key, raw Client configuration, command, or Docker control instruction.

## 3. Validation

Validation is atomic and rejects the entire new registry on any error:

- `version` must equal `1`;
- `devices` must contain 1 to 128 entries;
- every ID is unique and matches
  `^[a-z0-9][a-z0-9._-]{0,62}$`;
- display names are trimmed UTF-8, 1 to 128 characters, without control
  characters;
- expected FQDN is absent or a normalized lower-case DNS name no longer than
  253 characters; IP literals and URL syntax are rejected;
- `enabled` is explicit;
- `order` is an integer in `0..1000000`; ties sort by ID;
- tags contain at most 16 unique values, each 1 to 32 lower-case
  alphanumeric/`._-` characters;
- group is absent or 1 to 64 characters under the same label rules;
- `stale_seconds` is `30..86400`;
- `offline_seconds` is greater than `stale_seconds` and at most `604800`;
- `default_device_id` identifies an enabled registry entry;
- unknown JSON properties are rejected at every level.

`ingestion` is required and has this exact contract:

| Mode | Active protocol | Cutover expiry |
| --- | --- | --- |
| `legacy` | `legacy_single_device` | `null` |
| `device_v2` | `device_v2` | `null` |
| `cutover` | exactly one of the two protocols | required future RFC3339 UTC |

Only `active_protocol` may write. Cutover never enables both writers. An expired
cutover is a configuration error requiring an explicit final owner; it does not
fall back to last-write-wins.

Normalization is used only for comparison. It does not silently repair IDs or
invent missing values.

## 4. Ordering and visibility

The Server builds the device collection from the registry, never from the
currently connected set. Stable ordering is ascending `(order, id)`.

- Enabled, never-seen devices appear in stats and the selector.
- Enabled offline/stale devices remain visible.
- Disabled devices remain in the server-side state and stats with status
  `disabled`, but the default UI selector excludes them.
- Disabled devices cannot authenticate or update.
- An empty enabled set is a configuration error for serving a normal dashboard.

The browser receives only the safe registry projection required for display.
Tags/group may be emitted only after a separate UI requirement and security
review; they are not required in the first 2.2 stats contract.

Ingestion ownership exists only in the read-only registry. It is absent from
Client updates, credential records, persistence authority, and browser stats.

## 5. Registry and state merge

The merge key is only `device_id`:

| Situation | Result |
| --- | --- |
| Registry entry, no history | Create `never_seen` state |
| Registry entry plus history | Registry fields win; runtime observations merge |
| Display/FQDN/order changed | New registry value applies without changing identity |
| Device disabled | Keep history, reject updates, emit `disabled` |
| Device re-enabled | Keep history but require a new accepted update before online |
| Device removed | Retain internal orphan history; omit from normal stats |
| Same ID later restored | Re-associate validated history, still non-online until update |
| History with unknown ID | Keep as orphan; never auto-register |

Removal is therefore reversible and auditable. An operator must use a separate,
explicit retention procedure to purge orphan history; registry reload never
purges it.

## 6. Legacy mapping

Legacy `username` is not implicitly normalized into a new ID at runtime. A
deliberate compatibility mapping associates one existing username with one
registry ID. The mapping lives beside legacy authentication configuration, not
in browser stats. Duplicate mappings and mappings to disabled/missing IDs are
startup errors.

One legacy identity may correspond to only one Client connection, preserving
the current duplicate-connection rejection.

## 7. Failure behavior

- Missing/invalid registry at startup: Server does not enable 2.2 ingestion and
  reports a sanitized configuration error.
- Invalid reload: keep last known-good data; do not partially add/remove nodes.
- Registry beyond limits: reject rather than truncate.
- Duplicate ID: reject rather than let later entries overwrite earlier ones.
- Missing credential for an enabled device: device remains visible but cannot
  update; status is never promoted to online.

The registry is configuration, not a discovery database and not a source of
authentication secrets.
