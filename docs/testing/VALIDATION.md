# Release C stability and acceptance

Never infer a pass from missing data. Record timestamps, measurements, and sanitized evidence at each observation.

| Area | Checks at every observation |
| --- | --- |
| Go Server | RSS, CPU, goroutines, FDs, restart recovery, valid stats output |
| Python Client | process count, collector threads, CPU, RSS, SMART cadence, Docker Socket read, TCP update send |
| Runtime permissions | read-only rootfs, bounded tmpfs, `no-new-privileges`, writable stats/status binds, retained SMART/Docker/Hermes telemetry, and documented rollback of unsafe permission removal |
| Hermes Exporter | profile count, snapshot age, API fallback, CLI fallback, 401, timeout, stale semantics |
| Web | ten-minute refresh, manual refresh, page navigation, Profile modal, model/provider/source/mode, Docker page, browser request count |
| Security | no API key, Authorization, password, `.env`, raw config.yaml, Docker command, or raw smartctl output in logs/output |

Runtime permission acceptance must include a host-reboot check. Both containers must auto-start healthy, preserve their expected read-only rootfs, tmpfs, and `no-new-privileges` settings, keep restart counts at zero, and recover hardware, SMART, Docker, and Hermes telemetry. A dashboard sample captured before the first scheduled collector refresh must not be treated as a permanent API failure; verify the loopback health endpoint and then confirm the next ten-minute snapshot.
| Image provenance | exact OCI labels, full Git SHA, UTC build time, expected entrypoints, immutable image IDs, and no `.git` directory |
| Stats persistence | missing/empty/invalid input, atomic replacement, permissions, restart, down/up, recreation, backup, migration, rollback, multi-node selection, and dynamic Docker counts |

## Observation record

| Time point | Status | Evidence |
| --- | --- | --- |
| Immediately after deployment | Passed | Candidate deployment acceptance was completed |
| 1 hour | Passed | Continued operation was confirmed after candidate acceptance |
| 24 hours | Passed | User-confirmed weekend operation covers this checkpoint |
| Weekend run | Passed / User-confirmed | The user confirmed the deployed version ran stably for at least one weekend |
| Stats persistence deployment | Passed | Migration, restart, down/up, recreation, damaged-input recovery, and same-bind image rollback passed in the approved environment |
| Runtime hardening deployment | Passed | Read-only rootfs, bounded tmpfs, `no-new-privileges`, telemetry recovery, and host-reboot auto-start passed |
| 1.0 decommission | Passed | Offline package and image tar were verified before precise removal; 2.0 remained healthy after removal |
| 72 hours | Pending | Not elapsed |
| 7 days | Pending | Not elapsed |

The weekend result is user-confirmed. Later approved closure work directly checked container health, restart counts, HTTP responses, persistence, runtime permissions, and current telemetry, but did not collect a continuous CPU, RSS, goroutine, FD, or detailed time-series series. No exact weekend observation start or end time is inferred.

These checkpoints are not a formal performance benchmark, high-availability test, multi-node production validation, long-term SLA, Git tag, or GitHub Release. The 72-hour and 7-day checkpoints remain Pending until direct evidence establishes them.

## Coding-phase gates

Run migration contracts; all Go tests, race tests, vet, and build; both Python unittest suites; JavaScript syntax and Node tests; release-boundary/secret checks; both Compose config validations; both image builds; and Actions YAML validation when an available parser exists. A local pass is not evidence that GitHub Actions itself ran.

For image builds, pass the same provenance arguments to both Dockerfiles and run `scripts/validate_image_provenance.py`. Deployment validation remains Pending until an explicitly approved candidate is checked in its target environment.

Filesystem and migration-helper tests may run without Docker. Restart, down/up, and container recreation must use only a local Docker context and temporary data unless a separately approved production validation is active. Assertions must locate the target node by stable fields or extension domains rather than array position, fixed node count, or a fixed Docker total. Production persistence validation is recorded in [Stats Persistence](../operations/STATS_PERSISTENCE.md).
