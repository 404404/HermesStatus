# Configuration

Configuration is explicit.  Do not derive identity, environment or privileges
from a hostname, source address, port number or EasyTier overlay address.

## Server and Device Registry

The Server configuration defines the Device Registry and Device v2 credentials.
For each device, set a stable ID, operator-owned display name, protocol mode and
enabled state.  Device v2 credentials are provisioned separately: the Server
keeps only their digests and the Client receives its own token through a
root-owned secret file.

Do not auto-register devices or map a hostname, peer ID, overlay address or
source address to identity.  Validate configuration before restart with the
Server's device-configuration validation command.

## Client

Use one root-owned JSON configuration file per Client.  Its Device v2 section
contains the registry ID, HTTPS server URL, CA file and token file paths.
Mount token and CA as read-only secrets; never put tokens in image layers,
environment values, command lines, fixtures or documentation.

Optional domain configuration is explicit:

- `hardware.smart_devices` is a fixed disk allowlist;
- `hardware.filesystem_probes` is a fixed list of narrow read-only probe mounts;
- Lucky is loopback-only and uses an explicit TLS policy and optional token file;
- EasyTier uses a fixed local CLI, loopback RPC and an optional administrative
  role.  An omitted or empty optional role is not an invalid role.

For a complete device file, Compose mappings and field reference, see
[Device configuration](DEVICE_CONFIGURATION.md).

## Hardware privileges

Grant only the devices and paths that are needed.  SMART normally needs listed
devices plus `SYS_RAWIO`; it does not need privileged mode, `SYS_ADMIN`, a whole
`/dev` mount or an unrestricted host filesystem.  DSM identity and data-volume
probes, where needed, must be narrow read-only mounts specified by the
deployment, not broad defaults.

## Lucky local TLS

Lucky monitoring accepts only loopback URLs.  Configure HTTPS/HTTP and
certificate verification deliberately.  There is no automatic “verify then
disable verification” fallback.  If a local self-signed certificate requires
verification off, that exception must remain confined to the loopback-only
Lucky boundary and documented in the deployment configuration.

## UniFi monitoring (2.5)

UniFi V1 is disabled when the `unifi` object is absent, or when it is exactly
`{"enabled": false}`. To enable it, place all target details in the existing
root-owned Device v2 JSON file; no UniFi credential is accepted from an
argument or environment value:

```json
{
  "unifi": {
    "enabled": true,
    "profile": "udw",
    "host": "console.example.invalid",
    "port": 22,
    "username": "root",
    "credential_file": "/run/secrets/unifi-password",
    "known_hosts_file": "/run/secrets/unifi-known-hosts",
    "connect_timeout_seconds": 10,
    "interval_seconds": 60
  }
}
```

Only `udw` and `ucg-max` are valid V1 profiles. The selected profile is never
auto-detected from hostname, kernel, fans, temperatures, or observed values.
Mount both files read-only and make them regular, non-symlink files owned by
the Client effective user; the credential file mode must be `0400` or `0600`
and `known_hosts` must not be group/world writable. `StrictHostKeyChecking=yes`
is mandatory. Do not use `StrictHostKeyChecking=no`, a plaintext password
field, SSH keys added by HermesStatus, or an environment variable for the
credential.

The fixed core read only observes CPU temperature, aggregate CPU counters,
selected memory counters, uptime and load. Optional thermal/hwmon diagnostics
are non-health-affecting. Transport, host-key, authentication, timeout and
parse failures preserve the prior UniFi observation if one exists, mark it
stale, and never zero-fill metrics or degrade the Device v2 collector host.

UniFi `interval_seconds` is bounded to 30-180 seconds so the server freshness
window remains meaningful.
