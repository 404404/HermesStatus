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
