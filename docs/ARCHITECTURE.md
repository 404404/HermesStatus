# Architecture

HermesStatus is a small, read-only monitoring system.  A Client collects a
bounded set of host observations and sends them to the Server; the Server
validates and persists the accepted state; the web application reads the
Server's single statistics projection.

```text
host observations -> Client -> Device v2 HTTPS -> Server -> /json/stats.json -> web UI
```

## Device identity and data flow

The Device Registry is the authority for `device_id`, `display_name`, enablement
and protocol.  A Client-reported hostname is observation data only: it cannot
rename a Registry device.  Device v2 uses per-device credentials stored by the
Server as digests, TLS, replay/conflict checks and server-authoritative lifecycle
status.  Legacy reports remain supported where they are explicitly configured.

Accepted updates are atomic.  Stale, conflicting or invalid reports do not
replace the last accepted state.  After a Server restart restored data is stale
until a new accepted report arrives.

## Monitoring domains

The current projection contains independent read-only domains:

- hardware and operating-system observations;
- Docker;
- Hermes Agent profiles when the Agent is installed;
- Lucky;
- EasyTier;
- UniFi targets when an explicit Client-side profile is configured.

A domain can be fresh, partial, degraded, unavailable or not configured without
turning unrelated domains into failures.  In particular, an optional Hermes
Agent reported as `not_installed`, or a usable SMART attribute fallback, does
not alone make the device offline or unhealthy.

Hardware separates physical disks from volumes/filesystems.  This allows RAID,
device-mapper and DSM volumes to be displayed without pretending that a volume
belongs to one physical disk.

## Trust boundaries

Collectors use fixed allowlists and parsers.  They do not expose a remote shell,
arbitrary command runner, configuration editor or control plane.  Sensitive raw
objects, credentials, private endpoints and EasyTier configuration are not
persisted or displayed.  The web UI renders untrusted strings safely and shares
one stats document/fetch path across pages.

## EasyTier model

EasyTier is monitoring only.  The Client uses a configured loopback RPC and a
fixed read-only CLI path.  It has no commands for connectors, routes,
credentials, port forwarding, logging or service restart.  Profiles and routes
are normalized from a strict whitelist.  `supported`, `present` and `observed`
are distinct concepts; they are not inferred from zero RPM, an absent device or
a missing peer.

When no remote peer is observed, Direct, Relay and IPv6-UDP-Direct are
`not_observable`, not `false` or zero.  Current release limitation: some
EasyTier 2.6.4 output can include the local node in the peer list.  The remote
peer summary can therefore be overstated until the planned local-peer filter is
implemented.

## Deliberately out of scope

HermesStatus is not an EasyTier manager, a remote-execution service, an alerting
system, a time-series database, a topology editor, or a general network traffic
or carrier-probing product.

## UniFi model profiles

UniFi V1 is a remote-observation domain, not a second Client identity or a
control channel. A Device v2 Client runs one bounded, fixed OpenSSH session per
collection cycle and normalizes only symbolic sources: `ubnt-systool cputemp`,
aggregate `/proc/stat`, selected `/proc/meminfo`, `/proc/uptime`, and
`/proc/loadavg`. The Server receives a bounded telemetry projection only.

Profile selection is administrator-controlled and fail-closed. UDW and UCG Max
share the generic collector while their fan, PSU, thermal and NVMe differences
live in profile data. `supported`, `present`, and `observed` remain separate:
0 RPM, an unobserved block device, or an optional diagnostic source never
creates an inferred physical failure. UniFi transport failure marks only the
UniFi target stale; it never changes Device v2 identity or makes the collector
host offline.
