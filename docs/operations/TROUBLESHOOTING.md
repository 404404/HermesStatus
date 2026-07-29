# Troubleshooting

- Server unhealthy: inspect the resolved ports/mounts, `/api/health`, container restart count, disk space, and a bounded log tail for panic. Do not print tokens or raw configuration.
- Client stale/offline: confirm one Client process, TCP reachability to the configured Agent port, update timestamps, and collector intervals. Check permissions to mounted paths without dumping their contents.
- Hardware stale: verify hwmon/device visibility and SMART interval. Keep raw `smartctl` output out of reports and logs.
- Docker stale: verify the configured Socket exists and the collector can issue its constrained container-list GET. A read-only bind does not itself make the Docker API read-only.
- Hermes stale/error: distinguish API timeout/401 from CLI fallback failure, check snapshot age and profile count, and never log API keys, Authorization headers, `.env`, or raw Hermes configuration.
- Dashboard error: confirm `/json/stats.json` returns valid JSON and check browser network requests. Page switching should not issue requests; there should be one ten-minute interval.
- Image identity mismatch: inspect the OCI version, revision, creation time, source, image ID, and entrypoint. Compare them with the candidate record; do not print environment values or image history that may contain sensitive build commands.
- Stats persistence error: inspect the resolved `/app/data` mount, free space, directory type, ownership, and write permission. Missing, empty, or invalid JSON must not prevent startup; preserve damaged input for offline diagnosis without logging its contents. Do not create a second active stats snapshot.

Rollback when there is a restart loop, persistent HTTP failure, invalid/missing stats, semantic regression, secret exposure, or unacceptable resource growth.

Use [Build Provenance](BUILD_PROVENANCE.md) when distinguishing an expected artifact from a stale or locally rebuilt image.

Migration, backup, and recovery boundaries are documented in [Stats Persistence](STATS_PERSISTENCE.md).

If an operator expects a 1.0 listener or container, first confirm whether the request is an approved disaster-recovery exercise. The normal final state has no 1.0 Compose project, containers, network, images, ports, systemd unit, cron entry, reverse-proxy entry, or online directory. Use the checksummed offline package described in [Decommissioning HermesStatus 1.0](DECOMMISSION_1_0.md); do not reconstruct it from memory.

## HermesStatus 2.2 multi-device

- Startup validation failure: run `serverstatus --validate-device-config`
  against the same read-only mounts. Use only its fixed error code and field;
  do not dump Registry, credentials, mappings or paths.
- Registered device remains `never_seen`: confirm it is enabled, owns
  `device_v2`, has one active digest slot, and that the client uses the matching
  stable `device_id`. Never solve this by automatic registration.
- 401: treat unknown ID, missing credential and bad token identically. Check
  file ownership/mode and rotation window locally without logging the token.
- 403: check disabled/ownership/FQDN policy and the HTTPS/trusted-proxy
  boundary. Forwarded headers from an untrusted source must not enable the
  endpoint.
- Wrong dashboard device/name: confirm `servers[].device_id`, Registry
  `display_name`, hash fallback and localStorage selection. Client-reported
  name, hostname and FQDN are not display authority.
- After restart: restored devices must be stale/offline, never online, until a
  fresh accepted report. Preserve the persistence file and bounded orphan
  history while diagnosing.
