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

## EasyTier monitoring

EasyTier monitoring is opt-in and disabled by default. The client accepts these
non-secret settings, in descending precedence: EasyTier CLI options,
environment, a read-only JSON config file selected by `EASYTIER_CONFIG_FILE`,
then defaults.

| Setting | Default | Constraint |
| --- | --- | --- |
| `EASYTIER_ENABLED` | `false` | Explicit opt-in. |
| `EASYTIER_CLI_PATH` | `/usr/local/bin/easytier-cli` | Absolute executable regular file; symlinks are rejected. |
| `EASYTIER_RPC_PORTAL` | `127.0.0.1:15888` | Only `127.0.0.1:15888` or `[::1]:15888` is accepted. |
| `EASYTIER_TIMEOUT_SECONDS` | `5` | Integer from 1 to 30. |
| `EASYTIER_INTERVAL_SECONDS` | `30` | Integer from 5 to 3600. |

The JSON file may contain only `enabled`, `cli_path`, `rpc_portal`,
`timeout_seconds`, and `interval_seconds`; it must be a regular file not
writable by group or other users. Mount the CLI binary read-only into the
Client. Do not mount EasyTier configuration, keys, or a non-loopback RPC portal.

## Device v2 configuration

For the complete name/IP/port, file-path, and Compose-mount procedure, see the
[Device configuration guide](DEVICE_CONFIGURATION.md). Device Registry
`display_name` is the browser display-name authority; keep the Client URL under
operator control.

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

## Optional EasyTier expectation

Place an expectation only in the existing Registry device record when an
operator wants comparison diagnostics. It is optional and does not create a
device, authenticate a Client, or select credentials:

```json
"easytier_expectation": {
  "administrative_role": "site_router",
  "network_name": "home-404",
  "overlay_ipv4": "10.250.250.1",
  "proxy_cidrs": ["192.168.68.0/24"]
}
```

Allowed roles are `site_router`, `endpoint`, `bootstrap_listener`,
`relay_capable`, and `observer`; overlay and proxy values must be internal.
Only configure values deliberately. Missing observations are not failures by
themselves and display `not_observable`.
