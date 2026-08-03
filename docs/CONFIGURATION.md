# Configuration

[中文](zh-CN/CONFIGURATION.md) · [Documentation index](README.md)

## Server configuration

The Server reads a JSON document containing `servers`, optional `monitors`, and
optional `sslcerts`. A server entry needs a unique `username`, display `name`,
`type`, `host`, `location`, `password`, and `monthstart`. Do not commit a
production configuration or a real password.

| Variable | Purpose |
| --- | --- |
| `CONFIG_PATH` | Server JSON configuration. |
| `STATS_PATH` | Writable current-state persistence file. |
| `HTTP_ADDR` | WebUI and HTTP API listener. |
| `AGENT_ADDR` | Legacy TCP Agent listener. |
| `ADMIN_TOKEN` | Enables authenticated management APIs. |
| `WEB_DIR` | Static WebUI directory. |

When `ADMIN_TOKEN` is absent, public status endpoints remain available while
configuration-writing APIs are disabled.

## Client configuration

The Client needs a Server address, identity, password, and port for Legacy TCP:
`SERVER`, `SERVERSTATUS_USER`, `PASSWORD`, and `PORT`. `SERVERSTATUS_USER` is
the preferred name; `USER` is passed for compatibility and should not inherit
an accidental host value.

The Client also accepts paths and intervals for host collection. The important
ones are `HWMON_ROOT`, `SMART_DEVICE`, `DOCKER_SOCKET`,
`HARDWARE_INTERVAL`, `DOCKER_INTERVAL`, and `CLIENT_STATUS_DIR`.

## Hermes and Lucky

`HERMES_EXPORT_CONFIG` points to a JSON or YAML exporter configuration. It
defines the Hermes root and the named profiles to inspect. The exporter reads
configuration and status through read-only mounts and writes a sanitized
snapshot to the Client status directory.

Lucky collection is opt-in. Set `LUCKY_ENABLED=true`, provide
`LUCKY_BASE_URL`, and use `LUCKY_TOKEN_FILE` rather than embedding a token in a
Compose file. Keep `LUCKY_VERIFY_TLS=true` for HTTPS endpoints unless an
explicit, temporary compatibility decision requires otherwise.

## Device v2 configuration

Device v2 needs four operator-managed paths:

| Variable | Contents |
| --- | --- |
| `DEVICE_REGISTRY_PATH` | Read-only authoritative device registry. |
| `HERMESSTATUS_DEVICE_CREDENTIALS_DIR` | One digest-only credential file per v2 device. |
| `LEGACY_DEVICE_MAPPING_PATH` | Explicit legacy username-to-device mapping. |
| `PERSISTENCE_PATH` | Writable v2 runtime state. |

Enable the endpoint only with `HERMESSTATUS_DEVICE_ENDPOINT_ENABLED=true` and
an explicit trusted-proxy configuration. Validate the three read-only inputs
before startup:

```bash
serverstatus --validate-device-config \
  --device-registry /absolute/path/devices.json \
  --device-credentials /absolute/path/credentials.d \
  --legacy-device-mapping /absolute/path/legacy-device-mapping.json
```
