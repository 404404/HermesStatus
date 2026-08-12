# Device configuration guide

[中文](zh-CN/DEVICE_CONFIGURATION.md) · [Configuration](CONFIGURATION.md)

Device v2 keeps transport credentials separate from device presentation. This
lets an operator add a device deliberately, with its display name and endpoint
recorded in configuration instead of accepting a hostname reported by the
Client.

## Authoritative name and endpoint

The Device Registry `devices[].display_name` is the production name shown in
the device selector and dashboard. The Client-reported name is never allowed to
replace it. Use a stable operational name such as `GK50`, not a deployment
suffix such as `Preview`. Each Client keeps its own Server endpoint and HTTPS
port in `client-v2.json`, for example `https://status.example.invalid:21443`.

Use these files (production paths are examples, not repository files):

| Role | Host path | Container path | Mount |
| --- | --- | --- | --- |
| Device Registry | `/etc/hermesstatus/device-v2/devices.json` | `/etc/hermesstatus/devices.json` | read-only |
| Credential directory | `/etc/hermesstatus/device-v2/credentials.d` | `/etc/hermesstatus/credentials.d` | read-only |
| Legacy mapping | `/etc/hermesstatus/device-v2/legacy-device-mapping.json` | `/etc/hermesstatus/legacy-device-mapping.json` | read-only |
| Client configuration | `/etc/hermesstatus/device-v2/client-v2.json` | `/etc/hermesstatus/client-v2.json` | read-only |
| Device token | `/etc/hermesstatus/device-v2/secrets/gk50.token` | `/run/secrets/hermesstatus-device-token` | read-only |

## Server and Registry files

Start with the [Registry example](../config/examples/device-registry.example.json)
and, only when a Legacy TCP Client exists, the
[mapping example](../config/examples/legacy-device-mapping.example.json).
The mapping is not used to name or authorize Device v2 updates.

```json
{
  "id": "gk50",
  "display_name": "GK50",
  "enabled": true,
  "order": 10,
  "ingestion": {"mode": "device_v2", "active_protocol": "device_v2", "cutover_not_after": null}
}
```

The Registry never contains the token. Put only a SHA-256 digest in the
matching credential document.

## Client file

The Client endpoint is configured independently in `client-v2.json`. Its URL
contains the Server endpoint and HTTPS port; `device.name` is an identity hint,
not the browser display-name authority.

```json
{
  "version": 1,
  "server": {
    "url": "https://status.example.invalid:21443",
    "verify_tls": true,
    "ca_file": "/run/secrets/hermesstatus-ca.crt",
    "connect_timeout_seconds": 10,
    "read_timeout_seconds": 30
  },
  "device": {
    "id": "gk50",
    "name": "GK50 主机",
    "fqdn": null,
    "token_file": "/run/secrets/hermesstatus-device-token"
  },
  "collection": {"interval_seconds": 60},
  "hardware": {
    "smart_devices": [
      {"path": "/dev/sda", "type": null, "label": "data-disk-a"},
      {"path": "/dev/sdb", "type": "sat", "label": "data-disk-b"}
    ],
    "primary_smart_device": "/dev/sda",
    "filesystem_probes": [
      {"mountpoint": "/data", "probe_path": "/host-storage/data"}
    ]
  }
}
```

`url` must match the TLS certificate name or IP SAN. Keep the token file owned
by the Client user and mode `0400` or `0600`.

`device.id` is the stable Device v2 identity and is also the value used in the
browser selection hash (for example `#hardware?device=gk50`). Do not put
`preview` in a production-facing ID merely because the independent 21443
deployment is Preview. Renaming an existing ID is a controlled migration: back
up state, change the Registry device ID and default ID, rename/update the
matching digest-only credential document's filename and `device_id`, update
the Client JSON, and migrate the isolated Server state before restart. It is
not auto-registration and must never generate a new token or credential.

## Compose mappings

Apply the Server mounts with an override such as:

```yaml
services:
  serverstatus-server:
    volumes:
      - /etc/hermesstatus/device-v2/devices.json:/etc/hermesstatus/devices.json:ro
      - /etc/hermesstatus/device-v2/credentials.d:/etc/hermesstatus/credentials.d:ro
      - /etc/hermesstatus/device-v2/legacy-device-mapping.json:/etc/hermesstatus/legacy-device-mapping.json:ro
```

For each Client, mount its own configuration, token, CA, status directory, and
only the hardware paths that it is authorized to observe:

```yaml
services:
  serverstatus-client:
    environment:
      HERMESSTATUS_CONFIG_FILE: /etc/hermesstatus/client-v2.json
      # Leave blank so the JSON multi-disk allowlist is not overridden.
      SMART_DEVICE: ""
    devices: !override
      - /dev/sda:/dev/sda:r
      - /dev/sdb:/dev/sdb:r
    volumes:
      - /etc/hermesstatus/device-v2/client-v2.json:/etc/hermesstatus/client-v2.json:ro
      - /etc/hermesstatus/device-v2/secrets/gk50.token:/run/secrets/hermesstatus-device-token:ro
      - /etc/hermesstatus/device-v2/ca.crt:/run/secrets/hermesstatus-ca.crt:ro
      - /var/lib/hermesstatus/device-v2/gk50:/var/lib/serverstatus-client
      - /srv/example-data:/host-storage/data:ro
```

The base Client Compose file is non-privileged and maps no host block device,
so it starts on systems that do not expose `/dev/sda`. An audited override adds
`SYS_RAWIO` and `devices: !override` so paths match the JSON allowlist exactly.
Do not mount full `/dev`, use `privileged`, add `SYS_ADMIN`, or mount the host
root for filesystem capacity. Each filesystem probe needs its own narrow
read-only mount; it is sampled through `findmnt` and `statvfs`, never by
walking files.

`label` in `smart_devices` is collector configuration metadata. It is not a
promise that a label is persisted or rendered. Device, model, mountpoint, and
filesystem observations also cannot identify or authenticate the Client.

Validate Server inputs before restart:

```bash
serverstatus --validate-device-config \
  --device-registry /etc/hermesstatus/devices.json \
  --device-credentials /etc/hermesstatus/credentials.d \
  --legacy-device-mapping /etc/hermesstatus/legacy-device-mapping.json
```

Never commit the production configuration, token, digest documents, private CA,
or private endpoint addresses.

## Read-only diagnostics and provenance

The device information dialog is read-only. It may show Device ID, configured
display name, enabled/ingestion/protocol status, safe collection timestamps,
system identity, configured EasyTier expectation status, and Server/Client
build provenance. It must not show a token, digest, credential or Registry
path, source address evidence, private CA, or authorization header.

Set the environment label through the Server deployment, for example
`HERMESSTATUS_DEPLOYMENT_ENV=preview`; do not infer it from the current Preview
port 21443. Image builds inject version, revision, and build time. During
candidate qualification, compare the full Server and Client revisions with the
corresponding `org.opencontainers.image.revision` labels.

## EasyTier expectation example

The optional expectation is stored alongside the authoritative display name in
the Registry file (for example `/etc/hermesstatus/device-v2/devices.json`),
which the Server Compose file mounts read-only at
`/etc/hermesstatus/devices.json`. It does not belong in `client-v2.json` and
does not alter the Client's Server URL, port, authentication, or device ID.

```json
{
  "id": "gk50",
  "display_name": "GK50",
  "easytier_expectation": {
    "administrative_role": "site_router",
    "network_name": "home-404",
    "overlay_ipv4": "10.0.0.1",
    "proxy_cidrs": ["10.0.0.0/24"]
  }
}
```

Keep the existing required Registry fields in the real record; this abbreviated
example only documents the additional optional block. The Client EasyTier
configuration remains separately mounted and permits only its local CLI path,
loopback RPC portal, timeout, interval, and enabled flag.
