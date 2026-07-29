# HermesStatus 2.2 Multi-Device Protocol

Status: Stage A envelope/response/Client configuration contracts and pure mocks
frozen; no endpoint or network transport is active.

## 1. Current protocol audit

The 2.1 Client opens raw TCP, completes a `username:password` line handshake,
receives monitor definitions, then sends newline-delimited messages:

```text
update <current-flat-json>
```

The flat JSON contains native metrics plus structured `hardware`, `docker`,
`hermes`, and `lucky` domains and `extension_version`. Retained legacy
`hardware_json`, `docker_json`, and `hermes_json` fields are still decoded, with
structured data winning. Domain failures are isolated. The shared request limit
is 1 MiB.

Both Python Client variants currently duplicate configuration/protocol logic,
use `SERVER`, `PORT`, `USER`, `PASSWORD`, and `INTERVAL`, rely on a 30-second
socket default, and retry every three seconds. There is no TLS, URL model,
configuration file, separate connect/read timeout, or token file.

## 2. Transport decision

Production 2.2 uses verified HTTPS:

```text
POST /api/v2/device-updates
Content-Type: application/json
Authorization: Bearer <per-device-token>
X-HermesStatus-Device-ID: gk50-hermes
```

The Server URL is an origin, for example
`https://status.example.invalid`. The Client appends the fixed endpoint. The
first release rejects credentials, query, fragment, and path prefix in the
configured URL. It never follows redirects. HTTP is allowed only for explicitly
enabled loopback development and cannot be selected by a production profile.

## 3. Canonical envelope

The envelope wraps the existing flat stats object rather than duplicating every
domain schema:

```json
{
  "schema_version": 2,
  "device": {
    "id": "gk50-hermes",
    "reported_name": "GK50",
    "reported_fqdn": "gk50.example.invalid",
    "hostname": "gk50"
  },
  "collected_at": "2026-01-01T00:00:00Z",
  "stats": {
    "extension_version": "1.0-draft",
    "hardware": {},
    "docker": {},
    "hermes": {},
    "lucky": {}
  }
}
```

`stats` is exactly the current validated native-plus-extension update shape.
The Server passes it to the existing `decodeAgentUpdate`/domain decoders.
Therefore there is one Hardware/Docker/Hermes/Lucky contract and one ingestion
pipeline.

## 4. Envelope constraints

- root properties are exactly `schema_version`, `device`, `collected_at`,
  `stats`;
- `schema_version` must equal `2`;
- `device.id` is required, unique in the registry, and matches
  `^[a-z0-9][a-z0-9._-]{0,62}$`;
- `reported_name` and `hostname` are optional, trimmed, at most 128 and 253
  characters respectively, with control characters rejected;
- `reported_fqdn` is optional, lower-case-normalized for comparison, at most
  253 characters, and must be a DNS name rather than a URL/IP literal;
- `collected_at` is required RFC3339 UTC and subject to clock-skew limits;
- request size, including headers/envelope, is bounded; body remains at most
  1 MiB;
- strict decoding rejects unknown properties at new envelope/device levels;
- current stats and domain-specific array/string/object limits remain.

The payload cannot contain arbitrary metadata, `order`, `enabled`, authoritative
display name, freshness thresholds, `raw_response`, Client config, command,
token, cookie, password, or authorization material.

No `device_json` compatibility field is introduced. Existing
`hardware_json`, `docker_json`, `hermes_json`, and retained compatibility
parsers remain. `lucky_json` is not added.

## 5. Domain failure isolation

Envelope, authentication, and identity errors reject the whole request because
the target device is not safely established. Once identity is valid, each
business domain is decoded independently:

- a malformed Hardware domain does not remove valid Docker/Hermes/Lucky data;
- a failed collector emits the existing typed domain error/staleness behavior;
- absence, `not_configured`, `not_reported`, `stale`, and `error` keep current
  semantics;
- one device's domain failure never changes another device's state.

Native metrics and valid domains are accepted together under one server receipt
generation. Serialization failure in a later browser projection is isolated
again per device.

## 6. Response and monitor delivery

The current TCP handshake delivers monitor definitions. HTTPS must preserve
this capability without adding a control channel. A successful response is:

```json
{
  "accepted": true,
  "server_time": "2026-01-01T00:00:00Z",
  "config_generation": "synthetic-generation",
  "monitors": []
}
```

Monitor definitions use the current sanitized, bounded schema. They contain no
command, credentials, registry authority, or arbitrary executable
configuration. The Client caches only validated definitions and keeps the last
known-good definitions if a response is malformed. `202 Accepted` is used
because publication/persistence may complete after validation.

## 7. Client configuration

Both Python Client entry points will use one shared loader/transport module.
Final precedence is:

```text
explicit CLI options > environment variables > JSON config file > safe defaults
```

Required/optional values:

| Meaning | Environment variable | Rule |
| --- | --- | --- |
| Server origin | `HERMESSTATUS_SERVER_URL` | Required in v2; HTTPS production |
| Device ID | `HERMESSTATUS_DEVICE_ID` | Required; strict ID syntax |
| Reported name | `HERMESSTATUS_DEVICE_NAME` | Optional observation |
| Reported FQDN | `HERMESSTATUS_DEVICE_FQDN` | Required when registry expects it |
| Token file | `HERMESSTATUS_DEVICE_TOKEN_FILE` | Required, regular secure file |
| Config file | `HERMESSTATUS_CONFIG_FILE` | Optional, read-only JSON |
| TLS verification | `HERMESSTATUS_TLS_VERIFY` | Default `true` |
| Connect timeout | `HERMESSTATUS_CONNECT_TIMEOUT_SECONDS` | Default 10, range 1..60 |
| Read timeout | `HERMESSTATUS_READ_TIMEOUT_SECONDS` | Default 30, range 1..300 |
| Collection interval | `HERMESSTATUS_COLLECTION_INTERVAL_SECONDS` | Default 60, range 10..3600 |

Synthetic JSON configuration:

```json
{
  "version": 1,
  "server": {
    "url": "https://status.example.invalid",
    "verify_tls": true,
    "connect_timeout_seconds": 10,
    "read_timeout_seconds": 30
  },
  "device": {
    "id": "gk50-hermes",
    "name": "GK50 Hermes",
    "fqdn": "gk50.example.invalid",
    "token_file": "/run/secrets/hermesstatus-device-token"
  },
  "collection": {
    "interval_seconds": 60
  }
}
```

Unknown configuration keys and ambiguous `DOMAIN` variables are rejected.
Config and token mounts are read-only. CLI token values are forbidden; CLI may
set only the token file.

If any new 2.2 variable is set, incomplete 2.2 configuration fails closed and
does not silently fall back to a legacy password. Legacy `KEY=VALUE` arguments
and `SERVER`/`PORT`/`USER`/`PASSWORD` are recognized only when the complete new
configuration namespace is absent and legacy mode is explicitly available.

## 8. DNS, TLS, and retry behavior

Container DNS is supplied by its runtime/resolver configuration. The Client
uses normal address resolution and permits the networking stack to choose
reachable IPv6/IPv4 addresses; it does not pin a resolved IP across reconnects.

- certificate SAN must match the Server URL host;
- TLS verification is on with the system CA store by default;
- a custom CA is a separate read-only mount, never embedded as a token;
- normal certificate renewal requires no Client image rebuild;
- custom CA replacement may require safe Client reload/restart;
- redirects, especially cross-host redirects, are rejected;
- Server URL and device FQDN are never substituted for each other.

DNS, connect, TLS, read, and 5xx failures keep the Client process alive. Retry
uses full jitter with a 3-second base, factor 2, and 5-minute cap, reset after a
successful accepted report. `401`/`403` use the capped slow path and never print
credentials; `404` is treated as a deployment/version error; `429` honors a
bounded `Retry-After`. Recovery performs fresh DNS resolution and resumes
automatically.

## 9. Legacy adapter

The raw TCP adapter remains for 2.1 Clients. After its existing authentication,
it maps the legacy username one-to-one to a registry ID and internally creates:

```text
authenticated device_id + protocol_mode=legacy_single_device
                       + stats=<current flat update>
```

It then calls the same common ingestion method. One legacy identity still
allows one active Client, so multiple old Clients cannot overwrite one slot.
There is no automatic username-to-ID registration and no legacy body field that
can select a different device.

Before the common ingestion method is called, the registry ownership contract
must accept the adapter's protocol. `legacy`, `device_v2`, and timed `cutover`
each have exactly one active protocol; an inactive writer is rejected. Expired
cutover configuration accepts neither protocol until an explicit final owner is
configured.

## 10. Frozen Stage A boundary

Normative schemas are `schemas/device-update-v2.schema.json`,
`schemas/device-update-response-v2.schema.json`, and
`schemas/client-v2-config.schema.json`. The envelope `stats` member composes the
retained 2.1 domain schemas; it does not copy them. The Go/Python builders and
validators are pure mocks. No HTTP route, credential verification, DNS lookup, TLS
connection, token-file read, or existing Client entrypoint change is included.
