# Operations

[中文](zh-CN/OPERATIONS.md) · [Documentation index](README.md)

## Read-only checks

Start every investigation with the Server health document, the current stats
projection, and the Compose service state:

```bash
curl -fsS http://127.0.0.1:<web-port>/api/health
curl -fsS http://127.0.0.1:<web-port>/json/stats.json
docker compose -p <project> ps
```

Inspect only the fields relevant to the incident; never print credentials or
raw configuration.

## Interpreting data

An online device can still have a stale or unavailable hardware, Docker,
Hermes, or Lucky domain. Check each domain's `error`, `stale`, and update time
before treating a value as current. A SMART permission failure is unavailable
data, not a healthy disk and not a normal unknown state.

For Hardware, first compare the detailed `physical_disks` list with the
operator's explicit SMART allowlist and Compose `devices:` mappings. Then check
that `filesystems` contains only configured probe paths, not container root or
Docker overlay filesystems. A multi-disk host may intentionally omit legacy
singular SMART fields unless `primary_smart_device` was configured; use the
detailed storage record instead. A failed disk/probe must leave healthy peers
visible and mark only the affected item/domain degraded or unavailable.

System identity and build provenance are diagnostic evidence, not discovery.
Confirm the displayed Server/Client full revisions agree with the running image
OCI revision labels. Confirm the environment label is supplied by deployment
configuration, not inferred from the 21443 Preview port.

## Hardware diagnosis without widening access

Use the Client container's health/restart state, sanitized stats document, and
the reviewed Compose/configuration files. Do not fix missing SMART or capacity
by enabling privileged mode, mounting full `/dev` or host `/`, adding
`SYS_ADMIN`, or entering a host mount namespace. Instead, verify the exact
single-device mapping or add a separately reviewed read-only device/probe mount
that matches `client-v2.json`. Preserve a safe unavailable result when the host
cannot provide such a narrow mapping.

## Upgrade and rollback

Before change, record the Compose project, image IDs, source revisions, ports,
data paths, health state, and restart counts. Back up Server state and the
non-secret deployment configuration. Build and validate a candidate separately,
then recreate only the affected service. For 2.3 Preview, retain the independent
21443 project and its state/configuration backup; do not change 2.2 while
qualifying a Hardware update.

Rollback restores the recorded image reference and deployment configuration
while keeping the established Server data directory. Do not create a second
active writer or overwrite live state blindly.

## EasyTier interpretation

Read Collection Status before interpreting a detailed table. A command error or
timeout means that table is unavailable; it is not a genuine empty result.
`fresh` is assigned only after a new accepted report using the Server clock;
restored persistence begins stale until a new report. Zero remote peers is
healthy and makes Direct, Relay, and IPv6 UDP Direct `not_observable`.

The validated GK50 baseline is `2.6.4-8428a89d` with zero remote peers. Real
Synology dual-site, IPv6 UDP Direct, TCP fallback, a future remote private CIDR,
and Direct/Relay behavior remain qualification work, not operational failures.
