# EasyTier Monitoring Design

EasyTier support is a read-only Client domain. It collects a bounded projection
of node, peer, route, connector and traffic information through a fixed local
CLI and loopback RPC. It never manages EasyTier.

## Data model

The Server stores only validated, whitelisted fields. Node information,
collection status, peers, routes, connectors, traffic and optional configured
expectations are separate. Raw configuration, endpoint addresses, credentials,
keys and arbitrary feature objects are excluded.

Peer path is `direct` only with direct connection evidence and matching target /
next-hop IDs; it is `relayed` only with differing IDs; otherwise it is
`unknown`. Transport and address family are independent enumerations. With no
remote peers, Direct, Relay and IPv6 UDP Direct are `not_observable`.

An expectation is an operator diagnostic, not device identity. It may compare
network, overlay address, proxy CIDRs and administrative role. It cannot select
credentials, authenticate a device or auto-register anything.

## Collection semantics

Each fixed command reports its own status and time. A partial command failure
does not fabricate an empty list: it keeps last known data where available or
marks the particular data unavailable. The domain is fresh only after an
accepted report under the Server clock. An unknown schema/version is reported
as unsupported rather than passed through raw.

## Safety boundary

The runtime allowlist contains read-only queries only. It excludes connector,
route, credential, whitelist, port-forward, logger and service lifecycle
commands. RPC is loopback-only. The UI reads the existing stats document and
does not create an EasyTier control endpoint.

## Current limitation

Some EasyTier 2.6.4 output can include the local node in a peer-list response.
Current 2.0 may include that row in remote-peer summaries; the planned fix is a
strict own-peer-ID filter in normalization. Do not use affected summaries as
topology truth.
