# Upgrade

1. Record the running Compose project, resolved configuration, container names, image references/digests, ports, mounts, health, and stats path without printing environment values.
2. Back up Compose files, non-sensitive configuration, image references, and a necessary stats snapshot. Retain old images.
3. Build uniquely tagged Server and Client candidates from the reviewed worktree using the same `VERSION`, full `VCS_REF`, UTC `BUILD_DATE`, and public `SOURCE_URL`; do not use an uncommitted tree's HEAD as its content identity.
4. Validate both Compose configurations, then recreate only the services in the existing test project after explicit deployment approval.
5. Confirm container health, restart counts, `/`, `/api/health`, `/json/stats.json`, profile data, and absence of command/secrets in output and logs.
6. Observe immediately, then at 1h, 24h, 72h, and 7d. Record only measurements actually taken.

Schema extensions are backward-compatible and nullable/stale-aware, but Server and Client should be upgraded as one reviewed candidate to keep collection and rendering behavior aligned.

Validate both artifacts with `scripts/validate_image_provenance.py` and record immutable image IDs or registry digests. See [Build Provenance](BUILD_PROVENANCE.md).
