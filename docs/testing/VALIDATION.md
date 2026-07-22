# Release C stability and acceptance

Never infer a pass from missing data. Record timestamps, measurements, and sanitized evidence at each observation.

| Area | Checks at every observation |
| --- | --- |
| Go Server | RSS, CPU, goroutines, FDs, restart recovery, valid stats output |
| Python Client | process count, collector threads, CPU, RSS, SMART cadence, Docker Socket read, TCP update send |
| Hermes Exporter | profile count, snapshot age, API fallback, CLI fallback, 401, timeout, stale semantics |
| Web | ten-minute refresh, manual refresh, page navigation, Profile modal, model/provider/source/mode, Docker page, browser request count |
| Security | no API key, Authorization, password, `.env`, raw config.yaml, Docker command, or raw smartctl output in logs/output |
| Image provenance | exact OCI labels, full Git SHA, UTC build time, expected entrypoints, immutable image IDs, and no `.git` directory |

## Observation record

| Time point | Status | Evidence |
| --- | --- | --- |
| Immediately after deployment | Passed | Candidate deployment acceptance was completed |
| 1 hour | Passed | Continued operation was confirmed after candidate acceptance |
| 24 hours | Passed | User-confirmed weekend operation covers this checkpoint |
| Weekend run | Passed / User-confirmed | The user confirmed the deployed version ran stably for at least one weekend |
| 72 hours | Pending | Not elapsed |
| 7 days | Pending | Not elapsed |

The weekend result is user-confirmed. This documentation task did not reconnect to the deployment environment or independently collect measurements. No restart loop, page failure, or data interruption was reported by the user. No CPU, RSS, goroutine, FD, or detailed time-series values are asserted, and no exact observation start or end time is inferred.

These checkpoints are not a formal performance benchmark, high-availability test, multi-node production validation, long-term SLA, Git tag, or GitHub Release. The 72-hour and 7-day checkpoints remain Pending until direct evidence establishes them.

## Coding-phase gates

Run migration contracts; all Go tests, race tests, vet, and build; both Python unittest suites; JavaScript syntax and Node tests; release-boundary/secret checks; both Compose config validations; both image builds; and Actions YAML validation when an available parser exists. A local pass is not evidence that GitHub Actions itself ran.

For image builds, pass the same provenance arguments to both Dockerfiles and run `scripts/validate_image_provenance.py`. Deployment validation remains Pending until an explicitly approved candidate is checked in its target environment.
