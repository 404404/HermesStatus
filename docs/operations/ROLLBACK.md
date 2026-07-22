# Rollback

Rollback uses the recorded pre-deployment Compose configuration and immutable previous image IDs or registry digests. Never rely on a mutable tag alone, and never delete the old images during an upgrade.

1. Stop further candidate changes and capture current health/log summaries.
2. Restore the prior image references in the existing Compose project without altering ports or data mounts.
3. Recreate only affected services and wait for their existing health checks.
4. Verify `/`, `/api/health`, and `/json/stats.json`; confirm the stats directory remains intact.
5. If configuration changed, restore only the sanitized, pre-deployment configuration backup appropriate to that version. Do not overwrite live data blindly.

Exact commands depend on the discovered project and file paths and must be generated from the pre-deployment record, not guessed.

Compare the OCI revision, version, build date, and source labels against the deployment record before restoring an image. See [Build Provenance](BUILD_PROVENANCE.md).

For the primary stats-persistence rollback, keep the reviewed `/app/data` bind mounted and revert only Server and Client image references to the previous validated pair. Continue using the same persistent directory, then verify that the previous Server reads its stats file and that the Client repopulates current extension data. Do not merge two active snapshots or overwrite data while a writer is running. See [Stats Persistence](STATS_PERSISTENCE.md).

Removing the bind is a disaster-recovery-only path. A newly created container writable layer is empty and is not evidence of recovery; explicitly restore a validated stats backup before claiming success, and retain both the persistent directory and original backup throughout the recovery window.
