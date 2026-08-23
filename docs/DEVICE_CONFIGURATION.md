# Device Configuration

This guide describes the Device v2 configuration boundary. Examples use documentation-only addresses and placeholder secret paths.

## Paths and mounts

Typical host paths are root-owned:

| Host path | Container path | Purpose |
| --- | --- | --- |
| `/etc/hermesstatus/client-v2.json` | same path | Client configuration |
| `/etc/hermesstatus/credentials.d/<device>.token` | `/run/secrets/hermesstatus-device-token` | Device v2 token |
| `/etc/hermesstatus/ca.crt` | `/run/secrets/hermesstatus-ca.crt` | Server CA |
| fixed SMART devices | same device nodes | selected SMART observation |
| fixed empty filesystem probe directories | fixed `/host-storage/...` paths | selected filesystem observation |

All secret and probe mounts are read-only. Never mount all of `/dev`, the host root, a Docker socket or a package tree merely for observation.

## Device v2 file

```json
{
  "device": {
    "id": "example-device",
    "server": {
      "url": "https://status.example.invalid:443",
      "ca_file": "/run/secrets/hermesstatus-ca.crt",
      "token_file": "/run/secrets/hermesstatus-device-token"
    }
  },
  "hardware": {
    "smart_devices": ["/dev/sda"],
    "filesystem_probes": [
      {"mountpoint": "/data", "probe_path": "/host-storage/data"}
    ]
  }
}
```

The registry owns the display name. `device.id` is stable identity; do not use display names, addresses, hostnames or EasyTier peer IDs as replacements.

## Optional integrations

Lucky accepts an explicit loopback base URL, TLS policy and optional token-file mode. If a token is configured, mount only the token file under a fixed secret path. Empty token files are not a substitute for `auth_mode: none`.

EasyTier requires an explicit enablement decision, fixed read-only CLI path and loopback RPC endpoint. The optional administrative role may be omitted; an empty optional value has the same default semantics as omission. Known, non-empty roles are validated strictly.

## Synology/DSM notes

DSM storage is layered. Configure narrow read-only probes for the intended data volumes, and expose those volumes as filesystems rather than associating RAID `/dev/md*` volumes with individual member disks. A DSM identity source, when needed, must be a small read-only mount of the appropriate version file; do not mount broad system directories.

## Checklist

1. Create the Registry device and digest-only Server credential.
2. Write `client-v2.json` and root-owned token/CA files.
3. Validate Server and Client configuration.
4. Run a non-mutating preflight, then deploy an immutable image.
5. Confirm identity, HTTPS ingestion, fresh state and display name in the UI.
