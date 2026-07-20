# Architecture

HermesStatus is a read-only, single-host view combining Hermes Agent, host, hardware, SMART, and Docker state.

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

The Python Client performs OS, CPU, hwmon, SMART, and read-only Docker HTTP collection. The Hermes exporter builds sanitized per-profile snapshots using configured API checks and CLI fallback. The Client sends the structured extension in the existing TCP update.

The Go Server validates the extension, stores it on `NodeState`, and produces `SnapshotStats`. It serves static assets, health/API metadata, and `/json/stats.json`; it neither mounts Docker Socket nor reads Hermes configuration secrets.

The browser fetches only `/json/stats.json`. Home and Docker share one document in memory; navigation and the Profile Detail modal create no additional request. A single interval refreshes every ten minutes, while the toolbar provides manual refresh.

There is no history, database, alert engine, WebSocket, SSE, container control, or Hermes control plane.
