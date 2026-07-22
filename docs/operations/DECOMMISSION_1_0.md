# Decommissioning HermesStatus 1.0

## Contents

- [Final state](#final-state)
- [Resource classification](#resource-classification)
- [Offline recovery package](#offline-recovery-package)
- [Removal record](#removal-record)
- [Post-removal validation](#post-removal-validation)
- [Recovery boundary](#recovery-boundary)

## Final state

HermesStatus 1.0 is no longer running. Its runtime was removed only after Stats Persistence and Runtime Hardening were merged, deployed, and validated; the 2.0 Client had also been detached from the obsolete 1.0 status-directory bind. The Git `1.0` branch remains a frozen reference implementation.

This change does not remove Legacy wire compatibility from the Go Server. `hardware_json`, `docker_json`, and `hermes_json` remain **Retained Compatibility** as documented in the [Legacy protocol inventory](../migration/LEGACY_PROTOCOL_INVENTORY.md).

## Resource classification

| Resource | Classification | Final action |
| --- | --- | --- |
| Compose project `server-status` | 1.0 only | Removed |
| Containers `serverstatus-server` and `serverstatus-client` | 1.0 only | Removed |
| Network `server-status_serverstatus-network` | 1.0 only | Removed |
| Named volumes | None | No action |
| 1.0 Server and Client images plus protected backup image tags | 1.0 only | Saved offline, then removed |
| Former HTTP and Agent listeners | 1.0 only | Removed with the containers |
| Online deployment directory | 1.0 only after Client bind detachment | Archived, then removed |
| systemd unit/timer | None found | No action |
| cron entry | None found | No action |
| reverse-proxy entry | None found | No action |
| Git branch `1.0` | Frozen source reference | Retained |
| Current 2.0 data, network, images, configuration, and backup root | 2.0/shared operational state | Retained |

Unrelated stopped development containers, unused 2.0 networks, and non-runtime source directories were outside the approved 1.0 scope and were not deleted.

## Offline recovery package

The protected recovery directory is:

```text
/var/backups/hermesstatus/legacy-1.0-20260722T130245Z
```

The compressed package is:

```text
/var/backups/hermesstatus/legacy-1.0-20260722T130245Z.tar.gz
```

Its SHA-256 is:

```text
d5d0a9fdef3a2f25734d755369fe38582485b5925673a42963ecc526f07398cc
```

The directory is mode `0700`. The compressed package, image tar, manifest, copied configuration, and protected environment file are mode `0600`. Validation passed for file presence, tree-tar listing, Docker image-tar listing, per-file manifest checks, and the compressed-package checksum.

The package contains the complete online tree, Compose files, protected environment/configuration, stats and Hermes status data, redacted container/mount metadata, network and image identity, systemd/cron/proxy snapshots, listener and health records, deployed and remote Git references, recovery instructions, and four unique 1.0 image objects represented by their required tags.

Do not commit, publish, or attach the package. It may contain deployment secrets and host-specific data even though the operational report does not.

## Removal record

The exact Compose project was stopped with `down --remove-orphans` without `--volumes`. The two containers and dedicated network were removed. With no remaining container references, the archived 1.0 image tags and objects were removed without force or pruning. No named volume existed. The exact online deployment directory was then removed after confirming that no running 2.0 container mounted it.

No Docker system, image, or volume prune command was used. No 2.0 image, data directory, network, backup, Git branch, or unclassified resource was deleted.

## Post-removal validation

- No 1.0 Compose project or container remains.
- No dedicated 1.0 network, named volume, image, systemd unit/timer, cron entry, or reverse-proxy entry remains.
- The former 1.0 HTTP and Agent ports are not listening.
- The online 1.0 deployment directory is absent.
- The offline directory, compressed package, image archive, and checksums remain readable with their protected modes.
- The remote Git `1.0` and `2.0` branches remain present.
- Both 2.0 containers remained healthy with restart count zero.
- `/`, `/api/health`, and `/json/stats.json` returned HTTP `200`.
- The persistent Server data bind and Client status bind remained active.
- Hardware was current, SMART was `passed`, Docker was current, and all three Hermes Profiles reported healthy service/API/gateway state.
- The stats response contained zero forbidden secret-like keys and zero Docker command fields.

## Recovery boundary

Normal rollback uses a previous validated 2.0 Server/Client image pair with the same persistent stats directory. Restoring 1.0 is a separately approved disaster-recovery action:

1. Verify the package SHA-256 and internal manifest.
2. Extract into an isolated path.
3. Load the archived images.
4. Review protected configuration locally without printing secrets.
5. Select non-conflicting ports and a separate Compose project.
6. Validate health and stats before routing traffic.

Do not restore 1.0 automatically, delete the offline package, or delete the Git `1.0` branch as part of routine 2.0 maintenance.
