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
suffix such as `Preview`. Each Client keeps its own Server LAN IP and HTTPS port in
`client-v2.json`, for example `https://192.168.68.11:21443`.

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
contains the Server LAN IP and HTTPS port; `device.name` is an identity hint,
not the browser display-name authority.

```json
{
  "version": 1,
  "server": {
    "url": "https://192.168.68.11:21443",
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
  "collection": {"interval_seconds": 60}
}
```

`url` must match the TLS certificate name or IP SAN. Keep the token file owned
by the Client user and mode `0400` or `0600`.

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

For each Client, mount its own configuration, token, CA, and status directory:

```yaml
services:
  serverstatus-client:
    environment:
      HERMESSTATUS_CONFIG_FILE: /etc/hermesstatus/client-v2.json
    volumes:
      - /etc/hermesstatus/device-v2/client-v2.json:/etc/hermesstatus/client-v2.json:ro
      - /etc/hermesstatus/device-v2/secrets/gk50.token:/run/secrets/hermesstatus-device-token:ro
      - /etc/hermesstatus/device-v2/ca.crt:/run/secrets/hermesstatus-ca.crt:ro
      - /var/lib/hermesstatus/device-v2/gk50:/var/lib/serverstatus-client
```

Validate Server inputs before restart:

```bash
serverstatus --validate-device-config \
  --device-registry /etc/hermesstatus/devices.json \
  --device-credentials /etc/hermesstatus/credentials.d \
  --legacy-device-mapping /etc/hermesstatus/legacy-device-mapping.json
```

Never commit the production configuration, token, digest documents, private CA,
or private endpoint addresses.
