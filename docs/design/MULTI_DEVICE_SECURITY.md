# HermesStatus 2.2 Multi-Device Security

Status: Stage A security contracts and synthetic negative fixtures frozen; no
runtime security mechanism is activated.

## 1. Security objective

Multi-device support expands the ingestion and display cardinality, not the
Server's authority. It remains a monitoring system. This design adds no command
execution, container control, remote configuration, automatic registration,
tenant boundary, RBAC, or browser-to-Client channel.

## 2. Trust boundaries

| Boundary | Trusted authority | Untrusted input |
| --- | --- | --- |
| Registry | reviewed read-only Server config | Client-reported metadata |
| Credentials | separate read-only secret source | bearer/header/body |
| Transport | verified HTTPS endpoint | network/DNS/redirect response |
| Ingestion | authenticated ID + strict schema | every metric/domain value |
| Persistence | validated atomic snapshot | old/corrupt/unknown entries |
| Browser | safe stats projection | labels, IDs, errors, hash/localStorage |

The registry owns identity/display/order/enabled/freshness. The credential store
owns authentication. Neither is exposed to the browser.

The registry also owns ingestion write ownership. Exactly one protocol is
active for a device, including during cutover. Ownership never appears in a
Client body, credential record, persistence authority, or browser stats.

## 3. Threats and controls

### Cross-device overwrite

Authenticate one device ID, require header/body/registry/credential agreement,
capture the ID before decoding, and mutate only its map entry under lock.
Unknown/disabled devices are rejected. Request generations prevent an older
in-flight request from overwriting a newer one.

### Credential theft/replay

Use independent random tokens, read-only Client files, server-side digests,
verified HTTPS, bounded rotation windows, rate limiting, and secret-free logs.
Bearer tokens are replayable within their validity window, so exposure response
is immediate per-device rotation. Compromise of one token does not authorize
another device.

### Identity spoofing

Hostname/FQDN/source address are observations only. FQDN mismatch does not
redirect state to a different ID. Unknown devices never auto-register.

### Parser/resource exhaustion

Retain the 1 MiB body limit; cap devices at 128; bound all strings, arrays,
domain objects, config files, and token files; reject unknown envelope fields;
set read/connect/header timeouts; rate limit by authenticated identity and
network source. Domain decode failure remains isolated.

### Browser injection/data leakage

Render text with current escaping/text APIs; validate route IDs before DOM or
localStorage; never use raw Client values as HTML. Browser stats omit secrets,
credential mappings, full internal addresses, raw responses, and raw configs.

### Persistence poisoning

Use versioned strict decoding, atomic writes, size limits, validated IDs, and
registry-authoritative merge. Never promote unknown persisted entries into the
registry or mark restored data fresh.

## 4. FQDN and address exposure

Expected and reported FQDN values are needed internally for identity checks but
are `null` in browser-facing stats by default. The UI renders
`identity_status`, not raw values.

Exposing full FQDN requires an explicit global policy and deployment security
review. It must never happen merely because a registry entry contains one.
Internal IP lists are not added to the device collection. Existing domain
summaries keep their current sanitization/redaction and bounded output.

## 5. Transport policy

Production policy:

- HTTPS only;
- certificate verification always enabled;
- certificate SAN matches the configured Server host;
- no credentials/query/fragment/path prefix in Server URL;
- no redirect following, including same-host redirects in the first release;
- separate bounded connect and read timeouts;
- system CA store or explicit read-only custom CA;
- fresh DNS resolution on reconnect;
- fail-soft bounded exponential backoff.

Plain HTTP is limited to an explicitly enabled loopback test mode. It cannot be
activated by a Server response and is rejected for non-loopback hosts.

## 6. Secret handling

- one high-entropy token per device;
- token file mode `0400`/`0600`, regular, non-symlink, read-only;
- token never appears in CLI values, URL, body, cookie, logs, stats, errors,
  browser, registry, persistence, image layer, or repository;
- Server stores only token digests and validity metadata;
- compare digests in constant time;
- allow at most two active credentials during rotation;
- redact authorization/request bodies before generic HTTP access logging.

Credential records and registry files must be independently readable only by
the Server process/operator boundary.

## 7. Runtime hardening

The existing hardening remains a release gate:

- read-only root filesystem;
- `no-new-privileges`;
- bounded writable tmpfs/status locations only;
- read-only configuration, registry, token, credential, and custom-CA mounts;
- current capability/privileged/host namespace decisions are not broadened;
- no Docker control API or command endpoint is added.

Current Client host PID/network, privileged operation, device access, and
Docker socket exposure remain residual risks. Multi-device design must not add
mounts, capabilities, write access, or lateral network authority to address
unrelated features.

## 8. Logging, metrics, and errors

Safe observability fields:

- request ID;
- protocol mode;
- accepted/rejected outcome class;
- domain error code;
- bounded payload length and latency;
- non-secret credential slot name;
- a bounded device reference after syntax validation.

Never log authorization headers, request bodies, token/digest values, cookie,
password, private paths, raw collector responses, or credential mappings.
Public errors are generic; detailed audit events stay in the operator boundary.

## 9. Security validation gates

Tests must prove:

- Device A cannot update Device B by header/body/FQDN manipulation;
- every device token is isolated;
- unknown and disabled devices are rejected;
- credentials never enter stats, logs, errors, payload fixtures, or browser;
- credential comparison and body-ID checks occur before mutation;
- registry/credential/config/token mounts are read-only in deployment manifests;
- redirects and insecure TLS fail closed;
- malformed/oversized payloads are bounded;
- XSS and invalid route IDs do not enter DOM;
- no command/control endpoint or field exists;
- race tests cover concurrent distinct and same-device updates;
- runtime hardening, build provenance, and stats persistence checks still pass.

## 10. Non-goals and deferred decisions

Deferred:

- mutual TLS;
- tenant isolation/RBAC;
- token management UI;
- hardware-backed secrets;
- aggregate cross-device dashboards;
- public FQDN exposure;
- remote commands or Docker control.

These require separate threat models and cannot be inferred from 2.2 monitoring
approval.

Stage A contains no real credential, token digest, domain, address, production
path, HTTP listener, token-file read, DNS/TLS operation, or production config.
All negative fixtures are synthetic and the new pure modules are not imported
by production entrypoints.
