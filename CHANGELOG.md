# Changelog

## Unreleased — Release D Foundation

- Harden the Server and Client runtime with read-only root filesystems, bounded tmpfs mounts, `no-new-privileges`, and an explicit read-only Server config bind while retaining documented permissions that did not pass isolated removal tests.
- Archive the verified Release C feature and architecture baseline.
- Add release, deployment, upgrade, rollback, troubleshooting, validation, security, and limitation documentation.
- Add CI gates for Go, Python, migration contracts, frontend invariants, Compose, container builds, and repository secrets.
- Protect `2.0` with PR, current-head CI, conversation-resolution, administrator, force-push, and deletion gates; retain `1.0` as the legacy branch.
- Remove merged temporary branches for PRs #2 through #9 after PR, reachability, protection, and dependency checks.
- Record user-confirmed stable weekend operation while keeping the 72-hour and 7-day checkpoints Pending.
- Inventory the transitional `hardware_json`, `docker_json`, and `hermes_json` input compatibility without changing runtime behavior.
- Add consistent OCI build provenance for Server and Client images, including source revision, UTC build time, local validation, and deployment-record guidance.
- Move the default Server stats bind out of the WebUI tree, make its host directory configurable, add non-overwriting migration and persistence validation assets, and sanitize damaged-stats restore diagnostics.
- Complete the production stats migration to `/var/lib/hermesstatus/server`, including restart, down/up, recreation, same-bind rollback, checksums, and protected backups.
- Complete and deploy the Runtime Hardening baseline after isolated permission tests and a host-reboot recovery check.
- Retain the three Legacy JSON-string input fields as compatibility-only parsers with explicit removal gates.
- Archive the HermesStatus 1.0 runtime into a checksummed offline recovery package, remove its containers, network, images, ports, and online directory, and retain the Git `1.0` branch.
- No business feature, data-source, statistical-semantic, or page-layout changes.

## Release C — version pending confirmation

- Added the single-host Home and independent Docker views, responsive dashboard states, profile detail modal, ten-minute automatic refresh, and manual refresh.
- Consolidated browser reads on `/json/stats.json`; page navigation reuses the loaded snapshot.
- Removed Docker command data and presentation across the collection-to-browser path.
- Completed the Release A host/hardware/Docker and Release B Hermes profile foundations described in [Release C notes](docs/releases/RELEASE_C.md).
