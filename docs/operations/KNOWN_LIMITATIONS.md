# Known limitations

- Single-host current-state dashboard; no multi-node management experience.
- No history, database, trends, alert engine, WebSocket, or SSE.
- No container start/stop/exec or Docker command display.
- No Hermes runs, chat, stop, approval, or other control operation.
- No user system or RBAC; administrative Server APIs retain the upstream token boundary.
- SMART/hwmon availability depends on host hardware, kernel exposure, and Client permissions.
- Docker collection depends on a high-trust Socket mount; the code limits collection to listing containers, but the Socket itself is privileged.
- API/CLI fallbacks may produce stale/error states rather than fabricated values.
- Older deployment overrides may leave `/app/data` in the Server container writable layer. Stats must be backed up before container recreation unless preflight confirms a host bind or named volume.
- Stability observations at 24h, 72h, and 7d cannot be completed during the coding phase and remain Pending.
