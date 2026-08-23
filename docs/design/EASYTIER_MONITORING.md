# EasyTier Monitoring Design (2.3)

## Scope

HermesStatus 2.3 adds an opt-in, read-only EasyTier health projection to a
device's existing extension payload. It does not configure EasyTier, change
routes, add connectors, restart services, or expose an EasyTier management API.

The implementation is deliberately independent from the 2.2 deployment. A 2.3
preview uses its own Compose project, state, registry, credentials, and host
port.

## Trust boundary

```text
easytier-core loopback RPC
        ↓
easytier-cli JSON (five fixed read-only commands)
        ↓
strict Python projection
        ↓ authenticated Device v2 update
Go validation → atomic persistence v2 → /json/stats.json → WebUI
```

The browser never contacts EasyTier. The Go Server never mounts the EasyTier
binary, RPC socket, or host configuration.

## Collector contract

The collector uses an absolute executable path and `subprocess.run` with an
argv list and `shell=False`. Its command allowlist is exactly:

```text
node
peer
route
connector
stats
```

The RPC portal is restricted to `127.0.0.1:15888` or `[::1]:15888`; LAN,
overlay, wildcard, public, and hostname portals are rejected. The executable
must be an absolute, executable regular file and may not be a symlink.

Configuration precedence is CLI option, environment, read-only JSON file,
then defaults. Monitoring is disabled by default.

## Data minimization

Only a bounded projection is emitted: sanitized node identity/version, peer
facts, connector state, counter samples, derived RX/TX rates, and one status
per periodic command. A local peer entry is a valid observation; zero remote
peers remains healthy.

The payload never contains EasyTier config, credentials, keys, RPC portal,
arbitrary CLI JSON, command text, or stderr. `node.config` is stripped
immediately after decoding because it can carry `network_secret`. Only bounded,
credential-free listener/connector endpoints and selected STUN details are
projected. The Server rejects unknown fields and sanitizes secret-like strings
before persistence and UI projection.

## Failure semantics

Domain statuses are `healthy`, `degraded`, `unavailable`, `stale`,
`not_configured`, `unsupported_version`, and `invalid_data`. Command status is
recorded independently. A partial command failure preserves successful domains
and reports `degraded`; total RPC/CLI failure is `unavailable`.

## Compatibility

`easytier` is optional in the extension schema. Older clients and persisted v2
state that do not contain it are represented as `not_configured`; their updates
remain valid. Persistence writes the extra domain atomically when present.

## Verification targets

- Unit fixtures cover zero peer, direct/relay peers, TCP connector, partial
  command failure, configuration precedence, and secret/unknown-field rejection.
- The real-host qualification uses only the five commands above and records a
  sanitized projection.
- Preview must bind only its independent loopback host port and must prove the
  2.2 containers, configuration, and state were not changed.

## Detailed preview projection

The detailed view is still monitoring only. It projects bounded Node, Peer,
Route, Connector, and stats records from the five permitted loopback-RPC CLI commands:
`node`, `peer`, `route`, `connector`, and `stats`. Only internal overlay IPv4 and
RFC1918/RFC4193 proxy CIDRs may be retained. URL queries, credentials, raw
command output, and raw configuration are deliberately rejected.

Peer `cost` is retained verbatim; `p2p` is projected as `direct`, values
containing `relay` as `relayed`, and other values as `unknown`. `tunnel_proto`
is an established-tunnel set and cannot prove the transport of current business
traffic. With zero peers all three path results, including IPv6 UDP Direct, are
`not_observable`. TCP Listener Available, TCP Connector Configured, and TCP
Active are separate fields. The supported baseline is
`2.6.4-8428a89d`; compatibility is schema-family based for compatible 2.6.x,
while incompatible structures become `unsupported_version` rather than raw
JSON passthrough.

An optional Registry `easytier_expectation` compares configured administrative
role, network name, overlay IPv4, and internal proxy CIDRs with observations.
It is operator diagnostics only: it is never device identity, authentication,
registration, or credential selection. Missing observation is
`not_observable`; a command failure is not an empty list and leaves that view
unavailable. Synthetic fixtures cover future direct/relay/TCP/remote-CIDR and
failure states, and must never be described as real-network verification.
