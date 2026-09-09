# Operations

## Read status correctly

The Server lifecycle clock is authoritative. A restored state is stale until a new accepted report arrives. A healthy empty collection is distinct from an unavailable collection, and `not_configured` is distinct from an error.

Operationally degraded submodules remain visible. Do not convert these cases into a false device outage:

- optional Hermes Agent is not installed;
- a USB bridge exposes SMART attributes but not native return status;
- an EasyTier peer/route/connector collection is validly empty;
- an optional Lucky business module contains no configured objects.

Conversely, a genuine SMART failure, rejected Device v2 report or failed transport must remain visible as a failure/degraded state.

## Routine diagnosis

Start with the affected device's lifecycle state, update time and collection statuses. Compare Client snapshot, accepted Server projection and web view. For a deployment issue, compare running image digest and OCI revision to the intended immutable revision before investigating application behavior.

Use only documented fixed diagnostics. Do not enter containers, run arbitrary host commands or change router/Lucky/EasyTier configuration to diagnose a monitoring display issue.

## Backup and recovery

Back up Server state, registry configuration and non-secret deployment files before planned recreation. Preserve persistent state during a restart or Compose down/up test. Recover by recreating the affected service from a known exact image and configuration, then wait for a new accepted report before calling restored data fresh.

## Device v2 state upgrade and rollback

The first collection-diagnostics Server change after 2.7 persists structured
decode evidence and the explicit presence of EasyTier display-count metadata.
The on-disk state format still identifies as `version: 2`; therefore that
version string alone is **not** a downgrade compatibility guarantee. Isolated
compatibility validation established these two directions:

- an exact 2.7 (`c4e3fd30e60843373594c936fb62e5908062f685`) state restores with
  the newer Server;
- an exact 2.7 Server starts with newer state but rejects the affected device
  during restoration and retains it as a corrupt orphan.

Before upgrading the Server, make a private copy of the exact state file and
its `~` backup, record the Server and Client immutable digests plus the
configuration/registry revision, and retain them together. For a known
absolute state-file path, an operator can use:

```sh
STATE_FILE=/absolute/path/to/server-state.json
BACKUP_DIR=/absolute/path/to/rollback-before-server-upgrade
install -d -m 0700 -- "$BACKUP_DIR"
cp --preserve=mode,timestamps -- "$STATE_FILE" "$BACKUP_DIR/"
[ ! -e "$STATE_FILE~" ] || cp --preserve=mode,timestamps -- "$STATE_FILE~" "$BACKUP_DIR/"
sha256sum -- "$BACKUP_DIR"/*
```

A rollback across this boundary requires more than stopping the new Client:
stop it first to preserve the single Device v2 writer, stop the newer Server,
restore the exact prior Server/Client images and configuration, and restore
the pre-upgrade state copy before starting the older Server. Validate Compose
and then start Server before the matching Client; retain replay-protection
state and verify that only one writer is online. Without the pre-upgrade state
copy, this downgrade is not qualified: do not clear state or replay data just
to make the older Server start.

## EasyTier observation

Use “not observable” for Direct/Relay/IPv6-UDP-Direct when there are no remote peers. Current 2.0 has a known peer-summary limitation with some 2.6.4 output that lists the local node; validate detailed rows before treating the summary as a remote-peer count.
