# Stats Persistence

## Scope

The Server reads and atomically rewrites `STATS_PATH`, which defaults to `/app/data/stats.json` in the image. The `/json/stats.json` HTTP response is generated from the current in-memory snapshot; persistence restores selected native metadata and traffic baselines after a Server restart. It does not restore extension freshness.

## Selected storage model

The supported Compose file uses a configurable host bind:

```yaml
volumes:
  - "${SERVER_DATA_DIR:-./server-data}:/app/data"
```

The default keeps runtime data outside the WebUI source tree. Relative Compose bind sources resolve from the Compose project directory, so `./server-data` is a portable local default, not a production path recommendation. Production must set `SERVER_DATA_DIR` in its protected environment to a stable, explicit host directory that is outside `/tmp`, temporary extraction trees, and replaceable source checkouts. Confirm the resolved path before every deployment; a misspelled or empty override can cause Docker to create and use an unintended directory.

Bind storage was selected because operators can inspect, back up, migrate, and restore it without an extra Docker helper container. The deployment preflight must verify that the directory exists with the intended owner and mode before Compose starts; do not rely on Docker's automatic directory creation. Confirm free space, backup-system coverage, and applicable SELinux/AppArmor labeling. Compose project renames do not affect an absolute `SERVER_DATA_DIR`, but they can change the meaning of the relative default.

A Docker named volume would also survive restart and recreation and avoids host UID/path selection. It was not selected as the default because backup and migration require Docker volume tooling, and the current deployment model already uses host-managed files. A reviewed deployment may use a named volume if its backup and restore procedure is tested separately.

## Runtime behavior

- The current Server image has no `USER` directive and therefore runs as UID/GID `0:0`. This task does not change that permission model. The host directory must be preflighted for the actual runtime UID/GID, and future Runtime Permission Hardening must revisit ownership separately.
- The Server writes `stats.json` with mode `0644`.
- Writes use a temporary file in `/app/data`, file sync, atomic rename, and directory sync.
- A missing file is treated as no previous state and is created by the next stats cycle.
- An empty, invalid, truncated, or wrong-root JSON file does not block startup. The error identifies parsing failure without logging file contents; the next successful stats write replaces it atomically.
- A missing or unwritable directory produces a bounded filesystem error. Fix ownership or mount configuration; do not make the entire host path world-writable.
- Restart restores native traffic baselines, OS, and CPU model when node identity matches. Hardware, Docker, and Hermes extension objects restart as `not_reported` until the Client sends a fresh update.

Loss of the file does not change the HTTP route or browser contract, but monthly traffic baselines and retained native metadata can reset. The live page remains populated after the Client reconnects; extension freshness returns only after a new Client update.

## Migration

Keep the current data source untouched until the candidate has passed validation. The helper defaults to dry-run:

```bash
python3 scripts/migrate_stats_data.py \
  --source <existing-data-directory>/stats.json \
  --target-directory <new-data-directory>
```

After stopping writers through the separately approved deployment procedure, repeat with `--apply`. The helper validates a stats object, rejects secret-like fields and symbolic-link path components, and refuses an existing non-empty target. It rechecks the source and temporary-file SHA-256 before using a no-overwrite link, then syncs the target directory. It never stops containers, runs Compose, removes data, or overwrites a target. Dry-run performs no directory, temporary-file, or backup creation. Output contains only a generic source label, target file name, byte count, mode, and checksum, never stats content or node details.

Do not migrate an empty or invalid file. Do not overwrite an existing target. Keep the source directory and pre-change Compose configuration until restart, recreate, and rollback checks pass.

## Backup and rollback

Back up `stats.json` into a protected directory with file mode `0600`, recording the source revision and checksum without copying its content into logs. Test restoration into an empty temporary directory before deployment.

The primary rollback keeps the new `/app/data` bind and persistent directory, then restores only the previous validated Server and Client images. Verify that the previous Server reads the same stats file and that the Client repopulates current extension data. Never delete either source or target during the rollback window, merge two live snapshots, or restore over a running writer.

Restoring a Compose configuration with no bind is a disaster-recovery-only path. A new container writable layer starts empty; explicitly restore a validated backup before claiming recovery, and retain the persistent directory and original backup until validation is complete.

## Validation status

| Item | Status |
| --- | --- |
| Go filesystem persistence tests | Passed locally |
| Migration helper tests | Passed locally |
| Local persistence simulation | Passed using the local Docker context and temporary bind data |
| Local restart test | Passed |
| Local recreate test | Passed, including Compose down/up and container removal |
| Deployment migration | Pending |
| Production restart test | Pending |
| Production recreate test | Pending |
| Production rollback test | Pending |

Local validation is not production evidence. Deployment work requires a new explicit approval and a preflight that discovers the actual existing bind and project configuration.
