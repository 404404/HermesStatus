# Release C stability and acceptance

Never infer a pass from missing data. Record timestamps, measurements, and sanitized evidence at each observation.

| Area | Checks at every observation |
| --- | --- |
| Go Server | RSS, CPU, goroutines, FDs, restart recovery, valid stats output |
| Python Client | process count, collector threads, CPU, RSS, SMART cadence, Docker Socket read, TCP update send |
| Hermes Exporter | profile count, snapshot age, API fallback, CLI fallback, 401, timeout, stale semantics |
| Web | ten-minute refresh, manual refresh, page navigation, Profile modal, model/provider/source/mode, Docker page, browser request count |
| Security | no API key, Authorization, password, `.env`, raw config.yaml, Docker command, or raw smartctl output in logs/output |

## Observation record

| Time point | Status | Evidence |
| --- | --- | --- |
| Immediately after deployment | Pending | Requires an approved candidate deployment |
| 1 hour | Pending | Requires an approved candidate deployment and elapsed observation |
| 24 hours | Pending | Not elapsed |
| 72 hours | Pending | Not elapsed |
| 7 days | Pending | Not elapsed |

## Coding-phase gates

Run migration contracts; all Go tests, race tests, vet, and build; both Python unittest suites; JavaScript syntax and Node tests; release-boundary/secret checks; both Compose config validations; both image builds; and Actions YAML validation when an available parser exists. A local pass is not evidence that GitHub Actions itself ran.
