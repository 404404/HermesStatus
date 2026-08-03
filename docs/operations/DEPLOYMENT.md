# Deployment

## Supported topology

`docker-compose-server.yml` and `docker-compose-client.yml` are the supported Compose files. The Server image is built from `Dockerfile.server`; the Client image, which contains the Hermes exporter, is built from `Dockerfile.client`. There is no separate exporter image.

The Server persists stats under `/app/data` and mounts its configuration at `/app/config/config.json`. Its defaults expose HTTP `8080` on the host and Agent TCP `35601`. The Client uses host networking/PID, read-only host OS, hwmon, device, Docker Socket, and Hermes mounts, plus a writable status directory. Actual production paths and ports must be read from its Compose configuration and environment; never copy them into public documentation.

The active 2.0 deployment must not mount or read an archived 1.0 deployment directory. Hermes snapshots belong beneath the 2.0 Client status bind. Before removing an old deployment, inspect resolved Compose mounts and replace any obsolete compatibility bind with the 2.0-owned status directory.

## Configuration surface

The Server configuration surface is `ADMIN_TOKEN`, `HTTP_ADDR`, `AGENT_ADDR`, `CONFIG_PATH`, `STATS_PATH`, and `WEB_DIR`. The Client surface covers connection identity, probe settings, collection intervals, host OS/hwmon/SMART paths, Docker Socket and limits, status storage, and Hermes exporter paths, intervals, API limits, and host identity. Keep values in a protected deployment environment file; documentation and CI may name variables but must use only synthetic values.

The supported base Server Compose file binds `${SERVER_DATA_DIR:-./server-data}` to `/app/data`. The relative default resolves from the Compose project directory and is intended only for portable local use. Production must set `SERVER_DATA_DIR` in its protected environment to a stable, reviewed host directory outside temporary source or extraction trees. Before startup, verify the resolved absolute path, free space, backup coverage, directory ownership, and write access without printing environment contents. Older deployments may use `./web/json`, another host directory, or no persistent bind; discover and preserve that source before any recreate. Follow [Stats Persistence](STATS_PERSISTENCE.md) without overwriting existing data.

Build and artifact identity requirements are defined in [Build Provenance](BUILD_PROVENANCE.md). Record the full source SHA, UTC build date, OCI version, and immutable image ID or digest for both images before deployment. Tags alone are not rollback evidence.

Use a protected environment file outside version control. Validate before starting:

```bash
ADMIN_TOKEN=ci-placeholder docker compose -f docker-compose-server.yml config --quiet
SERVER=192.0.2.10 SERVERSTATUS_USER=<profile-name> PASSWORD=ci-placeholder docker compose -f docker-compose-client.yml config --quiet
docker compose -f docker-compose-server.yml build
docker compose -f docker-compose-client.yml build
```

For a candidate, build unique immutable local tags from the reviewed worktree. Reuse the target's existing environment and Compose project. Do not expose a new port or replace persistent data. Deployment requires explicit user approval and a pre-deployment backup.

Health endpoints are `/api/health` and `/json/stats.json`. The Server and Client images both declare health checks.

HermesStatus 1.0 is no longer an online rollback service. Its validated offline package and recovery boundary are described in [Decommissioning HermesStatus 1.0](DECOMMISSION_1_0.md).

## HermesStatus 2.2 multi-device deployment boundary

Development qualification does not authorize production deployment. Before a
separate 2.2 rollout, create a protected startup-only Registry (maximum 16),
one digest-only credential record per v2 device, explicit Legacy mappings and a
dedicated persistence-v2 bind. Validate them with
`serverstatus --validate-device-config` before starting any listener.

All startup configuration mounts must be absolute, normalized, read-only and
root/operator managed. Their host directory must not be group/world writable.
The Server traverses each document path through held directory descriptors and
opens the final regular file relative to its held parent; it does not use an
`lstat`-then-full-path-open sequence or an unsafe fallback. A secure-open or
validation failure is fatal before listeners or state writes.

The v2 endpoint is disabled by default. A production endpoint must be reachable
only through the exact HTTPS reverse-proxy POST location; the backend port must
not be public. Disable TLS 1.3 Early Data, replace external forwarding headers,
trust only the exact proxy address, and keep Registry, credential and mapping
mounts read-only. Follow [Manual Device Registration](MULTI_DEVICE_REGISTRATION.md)
and the [2.2 qualification report](../testing/MULTI_DEVICE_QUALIFICATION.md).
