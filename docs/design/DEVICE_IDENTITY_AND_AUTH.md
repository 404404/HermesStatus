# HermesStatus 2.2 Device Identity and Authentication

Status: Stage D public Internet authentication security contract implemented
locally; production activation remains disabled.

## 1. Current mechanism

The 2.1 TCP Server asks for a `username:password` line. It scans Server
configuration for the username, compares the configured plaintext password,
rejects disabled entries, and allows one active connection for that username.
The node map is keyed by username and subsequent updates are checked against the
connection ID.

This already isolates different configured usernames, but it is not the final
2.2 mechanism:

- password material is stored in Server configuration;
- the raw TCP transport does not provide TLS;
- username is overloaded as configuration identity and state key;
- there is no HTTP request/body identity binding;
- rotation has no first-class overlap procedure.

The existing password is not a single global token; it is configured per
username. Even so, plaintext password comparison and raw transport must not be
extended as the new production design.

## 2. Final identity rule

The stable key is `device_id`. It is assigned by the read-only registry and
matches `^[a-z0-9][a-z0-9._-]{0,62}$`.

For a 2.2 request, all four facts must agree:

1. `X-HermesStatus-Device-ID` header;
2. `device.id` in the request body;
3. an enabled registry entry;
4. the server-side credential record selected by that ID.

Reported hostname, reported display name, FQDN, source address, reverse DNS, and
TLS connection origin are never sufficient authentication identities.

## 3. Credential storage

Each Client receives an independent high-entropy bearer token through a
read-only secret file. The Server receives a separate read-only credential
directory. A credential record is named/resolved by validated `device_id` and
contains digests, never plaintext tokens:

```json
{
  "version": 1,
  "device_id": "gk50-hermes",
  "algorithm": "sha256",
  "credentials": [
    {
      "id": "current",
      "digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "not_before": "2026-01-01T00:00:00Z",
      "not_after": "2026-04-01T00:00:00Z"
    }
  ]
}
```

The placeholder above is not a usable credential. A production record contains
one or, during rotation, two independently generated token digests. SHA-256 is
acceptable only because each input is a CSPRNG-generated 32-byte (256-bit)
secret encoded as unpadded base64url. SHA-256 is not an acceptable password
hash for human-created passwords. Comparisons are constant-time.

Credential records are not part of the device registry, stats persistence,
browser document, API response, or logs. A registry entry without a valid
credential remains visible but cannot update.

## 4. Client token file

The Client configuration points to a regular file:

```text
HERMESSTATUS_DEVICE_TOKEN_FILE=/run/secrets/hermesstatus-device-token
```

Requirements:

- mode `0400` or `0600`;
- owner readable by the Client process;
- read-only mount;
- regular file, with symlinks rejected;
- exactly 43 ASCII characters after the optional line ending;
- exact token syntax `^[A-Za-z0-9_-]{43}$`, representing an unpadded base64url
  encoding of 32 CSPRNG bytes;
- exactly one trailing line ending may be removed;
- empty, whitespace-only, or embedded-control-character values are rejected;
- the value is never echoed, included in exceptions, or placed in a process
  argument or URL.

The Client sends `Authorization: Bearer <token>` over verified HTTPS. Query
parameters, cookies, and payload fields must not carry credentials.

## 5. Server authentication sequence

For `POST /api/v2/device-updates`:

1. enforce HTTPS at the trusted ingress;
2. reject unsupported method/content type/oversized body before parsing;
3. syntactically validate the device header without reflecting it;
4. validate the exact 43-character Bearer syntax and calculate SHA-256;
5. select the real credential set or the process-level fixed dummy digest;
6. execute exactly two constant-time digest comparisons, filling absent,
   inactive, malformed, or unknown slots with the dummy path;
7. reject unknown/missing credentials with the same generic `401`;
8. strictly decode the body and require body/header device IDs to match;
9. validate reported FQDN and other metadata;
10. call the common device ingestion path.

Recommended outcomes:

- `202`: accepted and state updated;
- `400`: invalid envelope;
- `401`: missing/invalid credential, with a generic challenge;
- `403`: known disabled device or authenticated identity/body mismatch;
- `404`: endpoint not supported, never used to reveal registry membership;
- `409`: stale report or equal-time canonical digest conflict;
- `413`: body exceeds the shared limit;
- `415`: unsupported content type;
- `429`: rate limited;
- `5xx`: transient Server failure.

Externally visible error bodies remain generic. Status choice must not become a
device-enumeration oracle; rate limiting and uniform logging apply.

## 6. FQDN identity evidence

If `expected_fqdn` exists:

- exact normalized match gives `matched`;
- absent reported value gives `missing_fqdn`;
- a different valid value gives `fqdn_mismatch`;
- invalid syntax rejects the envelope.

Policy for the first 2.2 rollout is fail closed for mismatch/missing evidence:
the request is authenticated but does not replace metrics or any public
`NodeState`. A registry device with no expectation receives `unknown`;
authentication still depends on its credential. Because a rejected mismatch
does not advance the accepted boundary, a corrected report with the same
timestamp may be accepted.

FQDN is not resolved to authenticate the Client. DNS results and source
addresses change and are not stable identity.

## 7. Isolation guarantees

- The authenticated ID is captured before body ingestion.
- Body ID mismatch is rejected before any `NodeState` mutation.
- Map lookup and mutation use only the captured authenticated ID.
- A request/connection generation prevents stale writers from replacing newer
  state for the same device.
- For Device HTTPS, canonical replay classification occurs under the
  per-device ingestion lock before identity rejection is acted on. Older
  reports return `409 stale_report`; equal-time same-digest reports return an
  idempotent `202`; equal-time different- or missing-digest reports return
  `409 report_conflict`. None of these paths modifies public state or
  persistence.
- Only a strictly newer request reaches FQDN policy. Missing or mismatched FQDN
  returns `403` without changing identity, freshness, generation, accepted
  boundary, business domains, or persistence. The same timestamp can therefore
  be retried with corrected identity evidence.
- Different devices use distinct state objects and credentials.
- Unknown identities are never auto-created.
- Disabled devices never update, even with a previously valid token.

The existing duplicate-connection rule stays for legacy TCP. HTTPS updates are
short requests, so “duplicate connection” becomes a per-device decision and
commit lock. Replay classification and the final commit share that critical
section; persistence serialization is the only required cross-device commit
lock. A newer accepted request therefore cannot be overwritten by an older
in-flight request.

## 8. Token rotation

Rotation is an operator-controlled, no-UI procedure:

1. generate a new high-entropy token outside the repository;
2. install its digest as `next` in the Server credential record;
3. atomically replace the Client token file while both digests are valid;
4. observe successful authenticated reports for the new credential ID through
   secret-free metrics/audit events;
5. retire the old digest after the overlap window;
6. securely discard the old plaintext token.

At most two credentials are valid per device. Each has explicit validity
timestamps. Rollback during the overlap restores the old Client secret file.
After retirement, rollback requires a newly reviewed rotation; expired
credentials are never silently re-enabled.

An operator may generate a candidate outside the repository with
`python3 -c 'import secrets; value=secrets.token_urlsafe(32); assert len(value) == 43'`
and must deliver it through the approved secret channel. This command is an
example only: no generated value is printed, executed, or stored in this
repository, and all repository tests use synthetic placeholders.

## 9. Logging and audit

Allowed fields: request ID, outcome class, protocol mode, bounded/hashed device
reference, latency, body length, and credential ID (`current`/`next`).

Forbidden fields: authorization headers, token/digest values, cookies, request
body dumps, raw Client configuration, passwords, and private paths. Parser
errors identify the domain/code and payload size only.

Audit events cover rejected unknown/disabled/mismatched identities, rotation
credential use, and rate limiting. Browser APIs never expose this audit stream.

## 10. Accepted residual risk

A valid bearer token is not sender-constrained during its validity window.
Bidirectional clock skew, per-device monotonic timestamps, and canonical
request-digest idempotency prevent an old or altered replay from replacing
newer state, but a stolen token may still submit a new current report.
Additional mitigations are verified HTTPS, disabled TLS 1.3 0-RTT, per-device
256-bit tokens, bounded current/next rotation, rapid per-device revocation,
secret-free logs, reverse-proxy path isolation, pre-auth and per-device rate
limiting, and an endpoint that is disabled by default. A future release may add
mTLS or another sender-constrained credential; neither is implemented by 2.2.

## 11. Legacy boundary

The TCP adapter retains its current password handshake only for 2.1 Client
compatibility. An explicit one-to-one mapping converts authenticated legacy
username to registry `device_id` and marks updates
`protocol_mode=legacy_single_device`.

No new 2.2 Client uses the raw TCP password flow. Legacy credentials are not
copied into the new token records, and a legacy username is not accepted as an
arbitrary 2.2 device ID.

The normative Stage A files are
`schemas/device-credential.schema.json` and
`schemas/legacy-device-mapping.schema.json`. Cross-file validation additionally
requires the mapped registry device to exist, be enabled, and have
`legacy_single_device` as its active ingestion owner. Stage A uses only
synthetic digests and never reads a token file.
