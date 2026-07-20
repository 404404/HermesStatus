# HermesStatus Release C

Status: code frozen on `origin/2.0`; version and release date require user confirmation. Release title recommendation: **HermesStatus Release C — Unified Read-only Status Dashboard**.

## Verified scope

- Host: CPU, memory, disk, uptime, host OS, and CPU model.
- Hardware: CPU temperature; current/highest/lowest disk temperature; SMART health; power-on hours; cumulative read/write bytes.
- Docker: running/total counts plus container name, image, status, and ports on an independent Docker page. Command collection and display are absent.
- Hermes: profile registry, health, gateway, API status, version, model, provider, model source, running mode, usage/auth mode, jobs, sessions, token usage, configuration summary, Docker volumes, Mixture of Agents, and Profile Detail.
- Dashboard: Home, Docker, responsive layout, empty/error/stale states, manual refresh, and one automatic refresh every ten minutes.

The browser reads only `/json/stats.json`. Home and Docker render the same in-memory snapshot, and switching pages does not fetch data.

## Architecture baseline

```text
Host / Hardware / SMART / Docker / Hermes
                  ↓
          Client / Exporter
                  ↓
        Structured TCP Update
                  ↓
          Go NodeState
                  ↓
          SnapshotStats
                  ↓
       /json/stats.json
                  ↓
           Home / Docker
```

The Go Server does not access the Docker Socket or read Hermes secrets. Host collection occurs in the Client/Exporter. There is no history store, database, alert engine, WebSocket, or SSE path.

## Compatibility and limitations

This release retains the ServerStatus TCP protocol and existing Compose deployment shape. It is a single-host, read-only current-state dashboard. See [Known limitations](../operations/KNOWN_LIMITATIONS.md) and [validation](../testing/VALIDATION.md).

## Release preparation

Suggested next version: `2.1.0` (minor), based on the repository's documented `2.0.0` baseline and the completed dashboard/Hermes capability set. No Git tag currently exists, so this recommendation must be confirmed before tagging.

Recommended annotated tag message: `Release HermesStatus 2.1.0: unified read-only status dashboard`.
