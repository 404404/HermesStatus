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

## Hardware collection

Hardware details are optional bounded observations. `hardware.storage` separates
physical disks from filesystems: a filesystem can resolve to one, many, or no
reported physical disks. This supports ordinary partitions, LVM, MD RAID,
device mapper, and Btrfs/EXT4 stacks without guessing that a logical volume is
a disk.

For Device v2, prefer the optional `hardware` object in `client-v2.json`:

```json
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
```

`smart_devices` is an explicit allowlist of 0–64 container-visible `/dev/*`
paths. Optional `type` is a bounded smartctl device type such as `sat`, `scsi`,
or `nvme`; it is not a shell fragment. `label` is collector configuration
metadata and is not promised as a persisted or UI display field.
`primary_smart_device` is optional and selects the compatibility singular SMART
fields when several disks are observed. Without it, those singular fields are
not arbitrarily taken from the first disk; detailed `storage.physical_disks`
remains authoritative.

`filesystem_probes` is an explicit list of up to 128 absolute display
`mountpoint` and container `probe_path` pairs. The probe path must be a
read-only mount of the intended host filesystem. The Client runs `findmnt` and
`statvfs` only; it never walks or uploads directory contents. Pseudo filesystems
and unavailable probes are reported as unavailable rather than presented as
host storage.

Configuration precedence is CLI, environment, JSON file, then defaults. The
environment alternatives are `HERMESSTATUS_SMART_DEVICES` / `SMART_DEVICES`,
`HERMESSTATUS_PRIMARY_SMART_DEVICE` / `PRIMARY_SMART_DEVICE`, and
`HERMESSTATUS_FILESYSTEM_PROBES` / `FILESYSTEM_PROBES`; JSON values are JSON
arrays. Legacy `SMART_DEVICE` remains the lowest-priority single-device form.
Do not set a legacy non-empty `SMART_DEVICE` in a Compose override that intends
the JSON multi-disk allowlist to be authoritative.

`auto` is retained for compatibility, but can discover only block devices
already visible to the Client container. It does not grant devices, change
cgroups, inspect unavailable host paths, or expand `/dev` access. See
[Hardware monitoring design](design/HARDWARE_MONITORING.md) for the data and
safety contract and [the device guide](DEVICE_CONFIGURATION.md) for Compose
mappings.

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
  "overlay_ipv4": "10.0.0.1",
  "proxy_cidrs": ["10.0.0.0/24"]
}
```

Allowed roles are `site_router`, `endpoint`, `bootstrap_listener`,
`relay_capable`, and `observer`; overlay and proxy values must be internal.
Only configure values deliberately. Missing observations are not failures by
themselves and display `not_observable`.
