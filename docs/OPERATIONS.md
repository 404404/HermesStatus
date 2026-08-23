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

## EasyTier observation

Use “not observable” for Direct/Relay/IPv6-UDP-Direct when there are no remote peers. Current 2.0 has a known peer-summary limitation with some 2.6.4 output that lists the local node; validate detailed rows before treating the summary as a remote-peer count.
