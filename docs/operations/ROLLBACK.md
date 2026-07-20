# Rollback

Rollback uses the recorded pre-deployment Compose configuration and immutable previous image references. Never delete the old images during an upgrade.

1. Stop further candidate changes and capture current health/log summaries.
2. Restore the prior image references in the existing Compose project without altering ports or data mounts.
3. Recreate only affected services and wait for their existing health checks.
4. Verify `/`, `/api/health`, and `/json/stats.json`; confirm the stats directory remains intact.
5. If configuration changed, restore only the sanitized, pre-deployment configuration backup appropriate to that version. Do not overwrite live data blindly.

Exact commands depend on the discovered project and file paths and must be generated from the pre-deployment record, not guessed.
