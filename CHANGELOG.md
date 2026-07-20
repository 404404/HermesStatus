# Changelog

## Unreleased — Release D Foundation

- Archive the verified Release C feature and architecture baseline.
- Add release, deployment, upgrade, rollback, troubleshooting, validation, security, and limitation documentation.
- Add CI gates for Go, Python, migration contracts, frontend invariants, Compose, container builds, and repository secrets.
- Protect `2.0` with PR, current-head CI, conversation-resolution, administrator, force-push, and deletion gates; retain `1.0` as the legacy branch.
- Remove merged temporary branches for PRs #2 through #9 after PR, reachability, protection, and dependency checks.
- Record user-confirmed stable weekend operation while keeping the 72-hour and 7-day checkpoints Pending.
- Inventory the transitional `hardware_json`, `docker_json`, and `hermes_json` input compatibility without changing runtime behavior.
- No business feature, data-source, statistical-semantic, or page-layout changes.

## Release C — version pending confirmation

- Added the single-host Home and independent Docker views, responsive dashboard states, profile detail modal, ten-minute automatic refresh, and manual refresh.
- Consolidated browser reads on `/json/stats.json`; page navigation reuses the loaded snapshot.
- Removed Docker command data and presentation across the collection-to-browser path.
- Completed the Release A host/hardware/Docker and Release B Hermes profile foundations described in [Release C notes](docs/releases/RELEASE_C.md).
