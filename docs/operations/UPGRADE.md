# Upgrade

1. Record the running Compose project, resolved configuration, container names, image references/digests, ports, mounts, health, and stats path without printing environment values.
2. Back up Compose files, non-sensitive configuration, image references, and a necessary stats snapshot. Retain old images.
3. Build uniquely tagged Server and Client candidates from the reviewed worktree using the same `VERSION`, full `VCS_REF`, UTC `BUILD_DATE`, and public `SOURCE_URL`; do not use an uncommitted tree's HEAD as its content identity.
4. Validate both Compose configurations, then recreate only the services in the existing test project after explicit deployment approval.
5. Confirm container health, restart counts, `/`, `/api/health`, `/json/stats.json`, profile data, and absence of command/secrets in output and logs.
6. Observe immediately, then at 1h, 24h, 72h, and 7d. Record only measurements actually taken.

Schema extensions are backward-compatible and nullable/stale-aware, but Server and Client should be upgraded as one reviewed candidate to keep collection and rendering behavior aligned.

Validate both artifacts with `scripts/validate_image_provenance.py` and record immutable image IDs or registry digests. See [Build Provenance](BUILD_PROVENANCE.md).

When adopting the independent stats directory, resolve `SERVER_DATA_DIR` from the actual Compose project directory and run `scripts/migrate_stats_data.py` without `--apply` first. The dry-run must not create directories, temporary files, or backups. Stop the writer only during a separately approved deployment window, apply into an empty preflighted target, preserve the original source, and validate restart and recreation before retiring rollback assets. See [Stats Persistence](STATS_PERSISTENCE.md).

The production migration has completed, but future upgrades must continue to resolve `/app/data` to the persistent directory and must not reintroduce a bind into the archived 1.0 tree. The normal rollback path is the previous validated 2.0 image pair on the same stats bind. Recreating 1.0 from its offline package is disaster recovery, not an ordinary upgrade step.
