# Deployment

## Supported topology

`docker-compose-server.yml` and `docker-compose-client.yml` are the supported Compose files. The Server image is built from `Dockerfile.server`; the Client image, which contains the Hermes exporter, is built from `Dockerfile.client`. There is no separate exporter image.

The Server persists stats under `/app/data` and mounts its configuration at `/app/config/config.json`. Its defaults expose HTTP `8080` on the host and Agent TCP `35601`. The Client uses host networking/PID, read-only host OS, hwmon, device, Docker Socket, and Hermes mounts, plus a writable status directory. Actual production paths and ports must be read from its Compose configuration and environment; never copy them into public documentation.

## Configuration surface

The Server configuration surface is `ADMIN_TOKEN`, `HTTP_ADDR`, `AGENT_ADDR`, `CONFIG_PATH`, `STATS_PATH`, and `WEB_DIR`. The Client surface covers connection identity, probe settings, collection intervals, host OS/hwmon/SMART paths, Docker Socket and limits, status storage, and Hermes exporter paths, intervals, API limits, and host identity. Keep values in a protected deployment environment file; documentation and CI may name variables but must use only synthetic values.

The supported base Server Compose file binds `./web/json` to `/app/data`. Older Release A/C override deployments may omit that bind and leave `STATS_PATH` in the container writable layer. Treat such a preflight result as non-persistent: copy the current stats file into the protected backup set before any recreate, and do not claim restart persistence until a reviewed host bind or named volume is present.

Use a protected environment file outside version control. Validate before starting:

```bash
ADMIN_TOKEN=ci-placeholder docker compose -f docker-compose-server.yml config --quiet
SERVER=192.0.2.10 SERVERSTATUS_USER=<profile-name> PASSWORD=ci-placeholder docker compose -f docker-compose-client.yml config --quiet
docker compose -f docker-compose-server.yml build
docker compose -f docker-compose-client.yml build
```

For a candidate, build unique immutable local tags from the reviewed worktree. Reuse the target's existing environment and Compose project. Do not expose a new port or replace persistent data. Deployment requires explicit user approval and a pre-deployment backup.

Health endpoints are `/api/health` and `/json/stats.json`. The Server and Client images both declare health checks.
