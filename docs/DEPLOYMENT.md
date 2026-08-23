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

## EasyTier preview and rollout

Keep an EasyTier-enabled candidate in a separate Compose project with a
separate registry, credential directory, state directory, client status
directory, and HTTPS host port. Bind that host port to the explicit private
interface used by the overlay or LAN (for example, the EasyTier interface),
never to `0.0.0.0` or a public address. Mount only the EasyTier CLI binary into
the Client, read-only; do not mount its configuration or secrets. If Device v2
uses a TLS proxy, set the Server's trusted-proxy CIDR to that proxy only and
keep backend HTTP private to the Compose network. Confirm `easytier.status`,
all four periodic command statuses, and the selected device in `/json/stats.json` before
any promotion. A zero remote-peer count is valid for a single-node overlay.

## Hardware, SMART, and filesystem access

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

The repository base `docker-compose-client.yml` is non-privileged and maps no
host block device by default, so it starts on SATA, NVMe, virtio, and similar
hosts. The complete Device v2 minimum-permission example at
`config/examples/docker-compose-client.override.example.yml` adds `SYS_RAWIO`
and replaces `devices:` only for an audited allowlist.

Keep the root filesystem read-only and retain `no-new-privileges`. A multi-disk
deployment is an explicit, individually reviewed device grant, for example:

```yaml
devices:
  - /dev/sda:/dev/sda:r
  - /dev/sdb:/dev/sdb:r
environment:
  # Leave empty when client-v2.json supplies hardware.smart_devices.
  SMART_DEVICE: ""
```

The matching `hardware.smart_devices` records in `client-v2.json` must name
only those same container-visible paths. Do not use `privileged`, mount all of
`/dev`, add `SYS_ADMIN`, or let automatic discovery expand device access.
RAID, LVM, and device-mapper are topology observations, not a reason to grant
their entire device tree. Confirm each physical SMART target first, including
any platform-specific smartctl type.

Filesystem capacity also requires an explicit read-only probe mount. This is a
safe example for one operator-selected data filesystem, not a host-root mount:

```yaml
volumes:
  - /srv/example-data:/host-storage/data:ro
```

Its Client JSON entry is `{ "mountpoint": "/data", "probe_path":
"/host-storage/data" }`. The Client performs metadata and `statvfs` checks
only; it does not enumerate files. If the desired host filesystem cannot be
presented as a narrow read-only probe, report it as unavailable rather than use
mount-namespace entry, `nsenter`, `CAP_SYS_ADMIN`, or privileged mode.

## Health check

After deployment verify:

```bash
curl -fsS http://127.0.0.1:<web-port>/api/health
curl -fsS http://127.0.0.1:<web-port>/json/stats.json
docker compose -p <project> ps
```

Check the Client's health and restart count, then confirm `hardware.storage`
contains the expected physical disks and only the configured filesystem probes.
An unavailable SMART record or filesystem probe is diagnostic data, not a
healthy value. For a single selected disk, the legacy singular SMART fields
remain available; with multiple disks use the detailed storage records and any
explicit `primary_smart_device`.

## 2.3 Preview staging

Use an independent Compose project, state directory, Registry, credentials,
network, and candidate images for `2.3-preview`. The current Preview host bind
is 21443 and must follow the existing staging bind policy; do not broaden it
while upgrading. Set the displayed environment through the deployment's
operator configuration (for example `HERMESSTATUS_DEPLOYMENT_ENV=preview`),
never by inferring it from 21443. Before a change, record 2.2 container IDs,
images, labels, ports, mounts, networks, and restart counts. Never stop,
recreate, or alter 2.2 as part of a 2.3 Preview deployment.

Build only from a clean candidate commit and label both Server and Client images
with its exact OCI revision. Back up the Preview config and state, upgrade the
existing Preview project without creating a competing writer, then verify
health, stats, Device v2 ingestion, persistence after Server restart and
down/up, and a zero-restart observation interval.
