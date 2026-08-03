# Deployment

[中文](zh-CN/DEPLOYMENT.md) · [Documentation index](README.md)

## Local Compose

The repository supplies `docker-compose-server.yml` and
`docker-compose-client.yml`. They are suitable for local validation after
reviewing their environment variables and bind mounts:

```bash
docker compose --env-file /secure/path/server.env \
  -f docker-compose-server.yml up -d --build

docker compose --env-file /secure/path/client.env \
  -f docker-compose-client.yml up -d --build
```

Use a protected environment file in production. Never place production tokens,
passwords, device credentials, or private addresses in this repository.

## Production boundary

Deploy a candidate as a separate Compose project with its own data directory,
client status directory, and host port. Verify it before replacing another
deployment. Record the full source revision and immutable image ID/digest for
both images. Tags alone are not sufficient provenance.

The Server exposes its WebUI/API listener and, when needed, its Legacy TCP
listener. If Device v2 is enabled, put only the v2 POST route behind an HTTPS
reverse proxy. Do not expose the backend device-update listener directly to the
internet.

## SMART device access

SMART collection needs a real block-device ioctl. Do not solve this by making
the Client privileged or by mounting the full `/dev` tree when a single disk is
being monitored. For a SATA disk at `/dev/sda`, the minimum Compose settings
are:

```yaml
cap_add:
  - SYS_RAWIO
devices:
  - /dev/sda:/dev/sda:r
environment:
  SMART_DEVICE: /dev/sda
```

This block replaces, rather than supplements, the legacy broad entries in
`docker-compose-client.yml`: set `CLIENT_PRIVILEGED=false` and remove its
`/dev:/dev:ro` volume before adding the capability and single-device mapping.
The supplied Compose file retains those legacy defaults for compatibility, so
leaving them in place would not be a minimum-permission deployment.

Keep the root filesystem read-only and retain `no-new-privileges`. If a host
uses another disk path or a RAID/NVMe controller, select and validate that
specific device before deployment. The Client must not receive a broader device
grant merely because automatic discovery is convenient.

## Health check

After deployment verify:

```bash
curl -fsS http://127.0.0.1:<web-port>/api/health
curl -fsS http://127.0.0.1:<web-port>/json/stats.json
docker compose -p <project> ps
```

Check the Client's health and restart count, then confirm that the selected
device has a non-unknown SMART status in `stats.json`.
