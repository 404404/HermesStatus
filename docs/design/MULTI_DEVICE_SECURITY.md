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

Use independent CSPRNG-generated 32-byte tokens encoded as exactly 43
unpadded-base64url characters, read-only Client files, server-side digests,
verified HTTPS, bounded rotation windows, rate limiting, and secret-free logs.
Application replay is bounded by bidirectional clock skew, per-device
monotonic timestamps, and canonical request-digest idempotency. Tokens remain
bearer credentials rather than sender-constrained credentials, so exposure
response is immediate per-device rotation. Compromise of one token does not
authorize another device.

An equal-time v2 report is idempotent only when both the incoming and persisted
canonical digests exist and match. State written before digest persistence was
introduced rejects equal-time reports as conflicts rather than guessing.
Replay classification is authoritative before FQDN policy: stale reports and
equal-time conflicts return `409`, even when their reported FQDN is missing or
mismatched. They cannot change identity, freshness, generation, accepted
boundary, business domains, or persistence. An exact equal-time replay returns
`202` without a second logical commit. Only a strictly newer request can reach
identity policy, and a rejected identity report does not advance the replay
boundary.

### Identity spoofing

Hostname/FQDN/source address are observations only. FQDN mismatch does not
redirect state to a different ID. Unknown devices never auto-register.

### Parser/resource exhaustion

Retain the 1 MiB body limit; cap registered devices at 16 and independent
orphans at 64; bound all strings, arrays,
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
registry or mark restored data fresh. Before listeners start, validate the
canonical primary path and its derived `~` backup unconditionally: the parent
must already exist, contain no symlink component, and be writable; both entries
must be missing or readable/writable regular non-symlink files with one link;
and the two entries must not alias the same inode. Repeat the same preflight
before accepting a device update and before every write. Persistence writes use
a held parent-directory file descriptor, `openat`/`renameat`, non-following
exclusive temporary files, file and directory sync, and explicit error
propagation.

HTTP and HTTPS monitor URLs never carry a query or fragment. This is a
structural deny-all rule, not a sensitive-parameter-name denylist, and applies
equally at configuration, Management API, reload, Device response, Fixture,
and Client boundaries.

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
- public traffic terminates at an HTTPS reverse proxy; the internal HTTP port
  is loopback/private only and is never directly exposed to the Internet;
- TLS 1.3 0-RTT/Early Data is disabled at the reverse proxy.

Plain HTTP is limited to an explicitly enabled loopback test mode. It cannot be
activated by a Server response and is rejected for non-loopback hosts.

## 6. Secret handling

- one high-entropy token per device;
- token syntax is exactly `^[A-Za-z0-9_-]{43}$`, produced by unpadded base64url
  encoding of 32 CSPRNG bytes;
- token file mode `0400`/`0600`, regular, non-symlink, read-only;
- token never appears in CLI values, URL, body, cookie, logs, stats, errors,
  browser, registry, persistence, image layer, or repository;
- Server stores only token digests and validity metadata;
- compare digests in constant time;
- allow at most two active credentials during rotation;
- redact authorization/request bodies before generic HTTP access logging.

Credential records and registry files must be independently readable only by
the Server process/operator boundary.

## 7. Layered rate limiting

The public boundary uses three independent layers: reverse-proxy source-IP
limiting, a bounded Server pre-auth source/global limiter, and a fixed-capacity
authenticated `device_id` limiter sized for 16 registered devices. Only an
explicit trusted proxy address or narrow CIDR may supply a regenerated source
address. Untrusted `X-Forwarded-For` never changes the key; an unreliable source
uses one bounded global unauthenticated key. Limiter state has TTL/capacity,
never contains headers or tokens, and never enters stats or persistence.

## 8. Runtime hardening

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

## 9. Logging, metrics, and errors

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

## 10. Security validation gates

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

## 11. Accepted residual risk

A valid bearer token is not sender-constrained during its validity window.
HermesStatus rejects reports outside the bidirectional five-minute clock
window, rejects timestamps older than the device's last accepted report,
treats an equal timestamp and canonical digest as idempotent, and rejects an
equal timestamp with different content. The digest is persistence-only and is
never emitted to Stats, logs, errors, fixtures, or the browser. A stolen token
can still submit a new current report, so future proxy mTLS or another
sender-constrained credential remains recommended and outside 2.2.

## 12. Non-goals and deferred decisions

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
