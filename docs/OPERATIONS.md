# Operations

[中文](zh-CN/OPERATIONS.md) · [Documentation index](README.md)

## Read-only checks

Start every investigation with the Server health document, the current stats
projection, and the Compose service state:

```bash
curl -fsS http://127.0.0.1:<web-port>/api/health
curl -fsS http://127.0.0.1:<web-port>/json/stats.json
docker compose -p <project> ps
```

Inspect only the fields relevant to the incident; never print credentials or
raw configuration.

## Interpreting data

An online device can still have a stale or unavailable hardware, Docker,
Hermes, or Lucky domain. Check each domain's `error`, `stale`, and update time
before treating a value as current. A SMART permission failure is unavailable
data, not a healthy disk and not a normal unknown state.

## Upgrade and rollback

Before change, record the Compose project, image IDs, source revisions, ports,
data paths, health state, and restart counts. Back up Server state and the
non-secret deployment configuration. Build and validate a candidate separately,
then recreate only the affected service.

Rollback restores the recorded image reference and deployment configuration
while keeping the established Server data directory. Do not create a second
active writer or overwrite live state blindly.
