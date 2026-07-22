# Troubleshooting

- Server unhealthy: inspect the resolved ports/mounts, `/api/health`, container restart count, disk space, and a bounded log tail for panic. Do not print tokens or raw configuration.
- Client stale/offline: confirm one Client process, TCP reachability to the configured Agent port, update timestamps, and collector intervals. Check permissions to mounted paths without dumping their contents.
- Hardware stale: verify hwmon/device visibility and SMART interval. Keep raw `smartctl` output out of reports and logs.
- Docker stale: verify the configured Socket exists and the collector can issue its constrained container-list GET. A read-only bind does not itself make the Docker API read-only.
- Hermes stale/error: distinguish API timeout/401 from CLI fallback failure, check snapshot age and profile count, and never log API keys, Authorization headers, `.env`, or raw Hermes configuration.
- Dashboard error: confirm `/json/stats.json` returns valid JSON and check browser network requests. Page switching should not issue requests; there should be one ten-minute interval.
- Image identity mismatch: inspect the OCI version, revision, creation time, source, image ID, and entrypoint. Compare them with the candidate record; do not print environment values or image history that may contain sensitive build commands.

Rollback when there is a restart loop, persistent HTTP failure, invalid/missing stats, semantic regression, secret exposure, or unacceptable resource growth.

Use [Build Provenance](BUILD_PROVENANCE.md) when distinguishing an expected artifact from a stale or locally rebuilt image.
