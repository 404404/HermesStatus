# HermesStatus 2.2 Multi-Device Migration

Status: Stage A mapping/ownership/persistence contracts and pure migration mock
frozen; no production migration is active.

## 1. Compatibility objective

2.2 introduces stable device identity without requiring an immediate flag day.
Existing 2.1 Clients, the current `servers[]` stats shape, legacy Web hashes,
and retained extension parsers continue to work during a defined migration
window.

Compatibility and migration are distinct:

- **compatibility** keeps old inputs/consumers operating;
- **migration** moves each device to the final registry, credential, HTTPS,
  persistence, and UI contracts.

## 2. Legacy Client mapping

Each permitted 2.1 username has one explicit mapping to one registry
`device_id`. It is validated at startup:

- username and device ID are unique on both sides;
- target device exists and is enabled;
- one legacy identity still allows one active TCP Client;
- no body field can change the mapped device;
- accepted legacy updates set
  `protocol_mode=legacy_single_device`.

The current username may be reused as the initial `device_id` only if it already
matches the ID syntax, is stable, contains no sensitive data, and an operator
explicitly chooses that mapping. It is never automatically promoted.

A new 2.2 credential and a legacy credential for the same registry device must
not update concurrently during normal migration. The Server enforces an
ownership mode (`legacy`, `device_v2`, or an explicitly timed cutover) so old
and new writers cannot flap one state slot.

The registry representation is:

```json
{
  "ingestion": {
    "mode": "cutover",
    "active_protocol": "device_v2",
    "cutover_not_after": "2099-01-01T00:00:00Z"
  }
}
```

The timestamp above is synthetic. During cutover, only the explicit active
protocol writes; the other is rejected. Expiry never opens both protocols and
requires an explicit final-owner configuration.

## 3. Protocol compatibility

The existing TCP handshake/update parser remains unchanged at the transport
edge. It feeds the common 2.2 ingestion path after mapping identity.

Retained and prohibited fields:

- retain `hardware_json`;
- retain `docker_json`;
- retain `hermes_json`;
- retain current structured-over-legacy precedence;
- retain current compatibility parsers;
- do not add `device_json`;
- do not add `lucky_json`;
- do not remove legacy parsing in the 2.2 release.

Legacy mode does not gain new authority. It cannot set registry display/order,
enabled state, expected FQDN, or device-level thresholds.

## 4. Stats compatibility

2.2 retains top-level `servers[]` and `updated`. It adds
`schema_version`, `generated_at`, `default_device_id`, and canonical fields
inside each server item.

During 2.2, existing item fields such as `name`, `type`, `host`, `location`,
native metrics, online flags, extensions, and retained JSON compatibility
fields are not removed. `name` mirrors registry `display_name` where safe.
Single-device fixtures normalize exactly as before; consumers that ignore
unknown properties keep working.

There is no second duplicated `devices[]` payload in the first 2.2 contract.
A later major contract may rename the collection only after consumer inventory,
deprecation, and fixture migration.

## 5. Persistence migration

Current persistence restores multiple nodes but matches mutable
name/type/host/location and intentionally does not make extensions fresh.
Persistence version 2 uses `device_id`.

One-time migration:

1. load and validate the registry and explicit legacy mappings;
2. read the old persistence snapshot without modifying it;
3. match each old entry only when one unambiguous mapping exists;
4. write a new versioned snapshot atomically;
5. keep an old-format backup until the rollback window closes;
6. place unmatched/ambiguous entries into `orphaned_devices`;
7. start all restored devices offline/stale until a new report.

No “best guess” matching by reported hostname/FQDN is allowed. Collisions stop
the migration. Separate traffic baselines remain per device. Extension data may
be preserved for display but its freshness is reset.

The frozen persistence v2 schema contains `version=2`, `generated_at`,
device entries identified by `device_id`, last accepted generation, last-seen
and collection times, protocol mode, snapshot status, runtime observations,
domain states, and `orphaned_devices`. Registry display/FQDN/order/enabled/
threshold/ownership fields and credential mappings are not persistence
authority. The Stage B v1 migration helper binds the complete legacy source
object through an explicit mapping table. It does not bind array indexes,
infer by hostname/FQDN, or promote usernames into device IDs. Unmatched or
removed records become orphans, and restored records are stale and non-online.
Operators must retain the original v1 file and a protected backup throughout
the rollback window; conversion never overwrites the v1 source.

## 6. Registry lifecycle

- Adding a device creates `never_seen`.
- Reordering/renaming does not affect history.
- Disabling preserves history and rejects all updates.
- Removing preserves orphan history internally and removes normal UI emission.
- Re-adding the same stable ID can restore history after validation.
- Reusing a removed ID for a different physical/logical device is prohibited;
  assign a new ID.

Retention/purge is an explicit later operation, not a registry side effect.

## 7. Rollout sequence

1. Ship schema fixtures, registry parser, persistence v2 reader/writer, and
   common ingestion path with legacy behavior still authoritative.
2. Populate the registry and validated one-to-one legacy mappings.
3. Enable new stats fields and multi-device UI while all Clients may still be
   legacy.
4. Provision per-device credentials and HTTPS transport separately.
5. Migrate one canary Client to `device_v2`; verify state, isolation, retry, and
   UI.
6. Migrate remaining Clients one at a time, switching device ownership mode.
7. Observe a full retention/freshness window.
8. Disable legacy ingress only in a later approved release after usage reaches
   zero and rollback criteria expire.

## 8. Rollback to 2.1 behavior

Rollback prerequisites:

- retain the old persistence snapshot and 2.1-compatible Server configuration;
- retain legacy credentials/mappings during the rollback window;
- do not destructively transform or purge extension compatibility fields;
- keep the prior image digests and provenance records;
- document which Clients have been switched.

Rollback procedure:

1. stop 2.2 Client ownership for affected devices;
2. restore the prior reviewed Server release/configuration;
3. restore the compatible persistence snapshot if the old reader cannot ignore
   v2 fields;
4. restart legacy Clients with their prior read-only configuration;
5. verify one writer per username and `servers[]` publication;
6. confirm Hardware/Docker/Hermes/Lucky freshness independently.

DNS, TLS, registry, credentials, images, and persistence are rolled back as
separate controlled layers. No force reset, silent state deletion, or
credential exposure is part of rollback.

## 9. Compatibility exit criteria

Legacy TCP retirement requires:

- no accepted `legacy_single_device` report for the agreed observation window;
- every enabled device has a verified v2 credential and HTTPS path;
- rollback window closed and backups retained per policy;
- contract consumers accept schema version 2;
- operations explicitly approve removing password/TCP support.

Removal is not part of the first 2.2 implementation.
