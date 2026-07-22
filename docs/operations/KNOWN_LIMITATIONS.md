# Known limitations

- Single-host current-state dashboard; no multi-node management experience.
- No history, database, trends, alert engine, WebSocket, or SSE.
- No container start/stop/exec or Docker command display.
- No Hermes runs, chat, stop, approval, or other control operation.
- No user system or RBAC; administrative Server APIs retain the upstream token boundary.
- SMART/hwmon availability depends on host hardware, kernel exposure, and Client permissions.
- Docker collection depends on a high-trust Socket mount; the code limits collection to listing containers, but the Socket itself is privileged.
- The Client remains privileged and uses host PID/network plus the read-only host device tree. These permissions preserve SMART auto-discovery, host process semantics, and loopback Hermes API access; a portable device/capability allowlist has not yet been proven.
- The Server retains its current capability set. A complete capability drop caused the published HTTP endpoint to fail during an isolated production test and was rolled back.
- API/CLI fallbacks may produce stale/error states rather than fabricated values.
- Older deployment overrides may use the former `./web/json` bind or leave `/app/data` in the Server container writable layer. Preflight must discover and preserve the existing source before adopting `SERVER_DATA_DIR`; deployment migration and production restart/recreate/rollback remain Pending.
- Immediate, one-hour, 24-hour, and weekend stability checkpoints have passed based on candidate acceptance and user confirmation. The documentation task did not independently measure the deployment; 72-hour and 7-day observations remain Pending.
