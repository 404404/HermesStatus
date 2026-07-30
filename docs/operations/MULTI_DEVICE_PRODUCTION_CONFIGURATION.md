# HermesStatus 2.2 Production Configuration and Remote Ingress

This guide is the operator-facing handoff for writing the 2.2 configuration,
understanding the authentication boundary, and exposing the device update
endpoint to Clients on other routed networks. It complements the detailed
[manual registration](MULTI_DEVICE_REGISTRATION.md),
[identity and authentication](../design/DEVICE_IDENTITY_AND_AUTH.md), and
[multi-device security](../design/MULTI_DEVICE_SECURITY.md) documents.

Do not copy production credentials, private hostnames, public addresses, or
certificate private keys into this repository.

## 1. Files and ownership

Keep server authority, client secrets, and runtime state separate:

| File | Contents | Recommended mode | Mount |
| --- | --- | --- | --- |
| `devices.json` | device IDs, display metadata, thresholds and ingestion ownership | `0640` | Server, read-only |
| `credentials.d/<device_id>.json` | SHA-256 digest and validity window only | `0600` | Server, read-only directory |
| `legacy-device-mapping.json` | explicit legacy username-to-device mapping | `0640` | Server, read-only |
| `client-v2.json` | Server URL, device ID, observation name and collection interval | `0640` | one Client, read-only |
| `<device_id>.token` | one 43-character bearer token | `0600` | matching Client only, read-only |
| `state-v2.json` | generated multi-device runtime state | Server-managed | Server, writable |

The three server configuration inputs are startup-only authority. The Server
does not edit or watch them. Validate and restart the Server after an approved
change. The persistence file is output, not configuration, and must never be
used to auto-register a device.

Use absolute, normalized host paths in production Compose files. Keep
credentials and tokens outside the source checkout, temporary directories,
images, and environment variables. Never mount a Client token into the Server
or another Client.

## 2. Write the server registry

Start from
[`config/examples/device-registry.example.json`](../../config/examples/device-registry.example.json).
Assign one stable, non-secret `device_id` to each logical device. The ID may
contain lowercase letters, digits, `.`, `_`, and `-`, and must not be reused
for different hardware.

For each entry:

- `display_name` is the operator-controlled UI name;
- `expected_fqdn` is either `null` or the exact Client-reported FQDN evidence;
- `enabled` controls visibility and update acceptance;
- `(order, id)` controls deterministic display ordering;
- `tags` and `group` are display metadata;
- `stale_seconds` and `offline_seconds` may inherit registry defaults;
- `ingestion` names the only protocol allowed to write that device.

Use one of these ownership blocks:

```json
{
  "mode": "legacy",
  "active_protocol": "legacy_single_device",
  "cutover_not_after": null
}
```

```json
{
  "mode": "device_v2",
  "active_protocol": "device_v2",
  "cutover_not_after": null
}
```

During a controlled migration, `mode` may be `cutover`, but
`active_protocol` still selects exactly one writer and
`cutover_not_after` must be an explicit RFC 3339 timestamp. Never allow
Legacy and v2 to write the same ID concurrently.

Set `defaults.default_device_id` to an enabled registry ID. Registry names and
ordering are authoritative; reported Client names and FQDNs are observations.

## 3. Create mappings and credentials

Every retained Legacy username must have one unique mapping:

```json
{
  "version": 1,
  "mappings": [
    {
      "username": "legacy-account",
      "device_id": "stable-device-id"
    }
  ]
}
```

The mapped registry entry must be enabled and owned by
`legacy_single_device`. A v2-owned entry must not retain an active Legacy
mapping after cutover.

Provision each v2 token offline with the repository helper:

```sh
python3 scripts/provision_device_credential.py stable-device-id \
  --client-token-file /secure/client/stable-device-id.token \
  --server-credential-file /secure/server/credentials.d/stable-device-id.json \
  --not-before 2026-08-01T00:00:00Z \
  --not-after 2027-08-01T00:00:00Z
```

The Client file contains the bearer token; the Server record contains only its
digest. The helper refuses existing targets unless an operator explicitly
uses the reviewed rotation procedure. Do not print, copy into a shell
argument, commit, or log the generated token.

## 4. Validate before activation

Mount the exact production files into the candidate Server image and run:

```sh
serverstatus --validate-device-config
```

Validation must succeed before the Server restart. It checks file safety,
schema and cross-file relationships, the 16-device limit, ownership, mapping,
and credential validity without opening listeners or writing state.

Before changing production:

1. back up the current Compose inputs, server configuration, stats and v2
   state;
2. record image digests and the exact source revision;
3. verify that the rollback images and configuration remain available;
4. start with all current devices under Legacy ownership;
5. dark-launch the 2.2 Server and confirm legacy reporting and persistence;
6. enable the protected HTTPS endpoint;
7. switch one registry ID and one Client to v2, then observe it before
   migrating another device.

## 5. Client configuration

Start from
[`config/examples/client-v2.example.json`](../../config/examples/client-v2.example.json):

```json
{
  "version": 1,
  "server": {
    "url": "https://status.example.net",
    "verify_tls": true,
    "ca_file": null,
    "connect_timeout_seconds": 10,
    "read_timeout_seconds": 30
  },
  "device": {
    "id": "stable-device-id",
    "name": "Observed Host Name",
    "fqdn": null,
    "token_file": "/run/secrets/hermesstatus-device-token"
  },
  "collection": {
    "interval_seconds": 60
  }
}
```

`server.url` must be an HTTPS origin with no credentials, query, fragment, or
path prefix. The Client appends the fixed
`/api/v2/device-updates` path. Leave `ca_file` as `null` for a publicly trusted
certificate. For a private PKI, mount only the issuing CA certificate
read-only and set its container path; never disable verification.

Server-side HTTP/HTTPS monitor targets are separate from `server.url`. They may
use a bounded path such as `https://example.net/health`, but must not contain
any query (including a trailing `?`), fragment, or UserInfo. If a health
endpoint requires a query credential, expose a credential-free dedicated
health path instead. `serverstatus --validate-device-config` reads the active
Server configuration with the same Monitor validator and rejects such a target
before startup.

The directory containing the v2 persistence file must exist before Server
startup and be writable by the Server process. The primary file and its
automatically derived `~` backup must be absent or readable regular files, must
be writable by the Server process, must not be symlinks/special files, and must
not be hard links to any other name.
Startup fails before listeners bind when this preflight fails; do not manually
bind either file to an external target.

The device ID must exactly match the header, request body, registry entry, and
credential filename. If `expected_fqdn` is configured on the Server, set the
Client `fqdn` to that exact normalized value.

Set only:

```yaml
environment:
  HERMESSTATUS_CONFIG_FILE: /etc/hermesstatus/client-v2.json
```

Mount the JSON and token read-only as shown in
[`config/examples/docker-compose-client.override.example.yml`](../../config/examples/docker-compose-client.override.example.yml).
Do not retain Legacy `SERVER`, `PORT`, username, or password variables in a v2
Client service.

## 6. Authentication architecture

The public request flow is:

```text
Client collector
  -> verified HTTPS and per-device bearer token
  -> exact-path reverse proxy
  -> trusted private HTTP hop
  -> header/body/registry/credential binding
  -> single-owner ingestion
  -> per-device state and persistence
  -> secret-free stats and Web UI
```

The stable identity is the operator-assigned `device_id`, not an IP address,
hostname, reverse DNS result, certificate origin, or Client-reported name.
Acceptance requires agreement between:

1. `X-HermesStatus-Device-ID`;
2. `device.id` in the strict request body;
3. an enabled registry entry;
4. the digest credential selected by that ID;
5. the entry's active ingestion protocol.

The Client sends a 256-bit random bearer token only over verified HTTPS. The
Server stores only SHA-256 digests and performs fixed-shape constant-time
comparisons. Invalid or unknown credentials receive a generic response.
Tokens, digests, authorization headers, request bodies, private paths, and
full private addresses are excluded from logs, stats, and browser APIs.

Bearer tokens are not sender-constrained. Protect them as host secrets, use
short reviewed validity windows and current/next rotation, and revoke one
device without changing any other device. See the
[normative authentication design](../design/DEVICE_IDENTITY_AND_AUTH.md) for
the exact validation order, replay rules, FQDN evidence, rotation, and accepted
residual risk.

Before migrating a canary, record its accepted generation, `last_seen`,
identity status, business values, and persistence checksum. Using synthetic
current-window payloads for that canary, verify in order:

1. an exact same-timestamp/body replay returns idempotent `202` without changing
   those values or the persistence checksum;
2. same timestamp with changed content and a mismatched FQDN returns
   `409 report_conflict`, not `403`, with no state change;
3. an older timestamp with a mismatched FQDN returns `409 stale_report`, not
   `403`, with no state change;
4. a strictly newer mismatched FQDN returns `403` without advancing the
   accepted boundary; and
5. a corrected identity report at that same timestamp is accepted and is
   durable across Server restart.

Do not run these checks with arbitrary real business observations. Stop the
canary v2 writer first, use a bounded synthetic payload, and retain the
validated Legacy rollback configuration until the observation window closes.

## 7. Give other networks a domain

Use a dedicated hostname such as `status.example.net`; do not expose the
Server container's HTTP or Agent TCP ports directly to the Internet.

### DNS and certificate

1. Create an `A` record, and an `AAAA` record only when IPv6 is actually
   routed and firewalled, pointing the hostname to the HTTPS ingress.
2. Obtain a certificate whose SAN exactly contains the hostname.
3. Automate renewal and test proxy reload without rebuilding Clients.
4. From every Client network, verify DNS resolution, the routed address,
   certificate chain, SAN, and expiry.

For private routed subnets, split-horizon DNS may return a private ingress
address while keeping the same hostname and certificate. If a private CA is
used, distribute only its CA certificate to Clients. Do not add insecure HTTP
fallback.

### Reverse proxy and firewall

Start from
[`config/examples/reverse-proxy.nginx.example.conf`](../../config/examples/reverse-proxy.nginx.example.conf).
The public virtual host must:

- expose only exact `POST /api/v2/device-updates`;
- return `404` for every other path and reject every other method;
- allow TLS 1.2/1.3 while disabling TLS 1.3 early data;
- enforce bounded body, header and timeout limits;
- disable redirects, caching and request-body logging;
- preserve `Authorization` without logging it;
- replace untrusted forwarding headers and set
  `X-Forwarded-Proto: https`;
- proxy only to a loopback address or private container network.

Permit inbound TCP 443 to the reverse proxy from the intended networks.
Firewall the Server HTTP backend and Legacy Agent TCP port from public and
untrusted networks. If the proxy and Server use a Docker network, expose the
backend only on that internal network rather than publishing it on the host.

Enable Server trusted-proxy mode only after recording the proxy's exact private
address or a narrowly scoped CIDR:

```yaml
environment:
  HERMESSTATUS_DEVICE_ENDPOINT_ENABLED: "true"
  HERMESSTATUS_DEVICE_TRUSTED_PROXY: "true"
  HERMESSTATUS_DEVICE_TRUSTED_PROXY_CIDRS: "192.0.2.10/32"
```

The address above is documentation-only. Never trust an entire bridge, LAN, or
public range when the proxy has a stable narrower address. A request that
bypasses the configured trusted proxy must fail closed.

### Acceptance checks

From a Client network, verify:

- the hostname resolves to the intended ingress;
- TLS hostname and chain validation succeed;
- HTTP and IP-address URLs fail;
- the exact POST path reaches the Server without redirect;
- a missing/wrong token is rejected generically;
- the correct device updates only its own registry ID;
- Server and proxy logs contain no authorization value or request body;
- DNS, proxy, Server, and Client restarts recover without a retry storm.

Keep public DNS/TLS changes, Server activation, and Client ownership cutover as
separate rollback layers.
