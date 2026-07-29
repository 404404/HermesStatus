# HermesStatus 2.2 Multi-Device Qualification

Status: Stage F source-candidate qualification passed locally. No production
service, network, directory, registry, credential, DNS record or certificate
was read or modified.

## Candidate identity

The source candidate was
`78007feabf44ed4ba44949fcf3a61949314b24a6`.

| Image | Tag | Image ID / local RepoDigest |
| --- | --- | --- |
| Server | `hermesstatus-server:2.2-78007feabf44` | `sha256:90251d7883b2f00f9a830bae644eb620f954cf1ac2a867f71d6ba2aad7b01a15` |
| Client | `hermesstatus-client:2.2-78007feabf44` | `sha256:126e5d5c7d507de9697ddfe39cd1434011daccef2078c7f2c9e805580cd32355` |

Both images were `linux/amd64`. Server entrypoint was
`/usr/local/bin/serverstatus`; Client entrypoint was `/app/entrypoint.sh`.
The OCI version was `2.2-78007feabf44`, revision was the full candidate SHA,
creation time was `2026-07-29T15:33:50Z`, source was the repository URL, and
license was `MIT`.

These local image identities are evidence for the source candidate only.
The merge workflow must rebuild with the final merge SHA and repeat the
qualification before development can be declared complete.

## Isolated deployment

The deployment used a new Docker bridge with an RFC1918 test subnet, no
published ports, no production network, read-only root filesystems,
`no-new-privileges`, bounded tmpfs mounts, and a new mode-0700 temporary data
root. It contained one candidate Server and four candidate Client containers.
Registry, credentials, token files, legacy mapping and persistence were
entirely synthetic. The legacy runtime input was the checked-in
`testdata/server-runtime-synthetic.json` placeholder fixture.

The four registry states were:

| Device | Expected state | Observed state |
| --- | --- | --- |
| `compute-01` | accepted healthy v2 update | `online`, CPU fixture 21 |
| `storage-01` | accepted degraded v2 update | `degraded`, CPU fixture 62 |
| `legacy-01` | no update after restore | `offline` |
| `disabled-01` | registered but disabled | `disabled` |

Before any update, the enabled devices were visible as `never_seen` and the
disabled device as `disabled`. Restart, stop/start and force recreation reused
the same synthetic persistence bind. Restored devices were never restored as
online; fresh authenticated reports were required.

The candidate binary's `--validate-device-config` ran with `--network none`
and reported four devices, three enabled, one disabled, three v2 credential
records, one legacy mapping and the expected default ID. It created no
listener or output file.

## Authentication and proxy matrix

The candidate Client image sent strict envelopes from the one explicitly
trusted proxy address. The proxy-equivalent path replaced external forwarding
headers and supplied exactly one `X-Forwarded-Proto: https`. Results were:

| Case | Result |
| --- | --- |
| valid `compute-01` credential and identity | 202 |
| valid degraded `storage-01` report | 202 |
| disabled registered device | 403 |
| unknown device | generic 401 |
| compute header/token with storage body | 403 |
| wrong fixed-length token | generic 401 |
| `/api/v2/device-updates/command` | 404 |

The same request from an address outside the configured trusted proxy set with
a forged forwarded-proto header returned 403. The accepted compute and storage
values remained isolated. Client-reported names did not replace the Registry
labels `Synthetic Compute` and `Synthetic Storage`.

Verified TLS, CA, SAN, expiry, redirect and direct/proxy boundaries are also
exercised by `clients/test_device_client_tls.py` and
`TestDeviceEndpointTransportAndTrustedProxyBoundaries`. TLS 1.3 Early Data is
disabled by the checked reverse-proxy configuration.

## Scale and lifecycle

The candidate validator loaded the checked-in 16-device registry together
with 16 independently generated digest records and zero legacy mappings:

```text
validation success
total devices: 16
enabled count: 16
disabled count: 0
credential records count: 16
legacy mappings count: 0
default device_id: synthetic-000
```

The 17-device registry exited 2 with only:

```text
validation failed code=registry_invalid field=registry.devices
```

Atomic 17-credential, 17-legacy-mapping and 17-active-migration rejection,
16-device serialization/order/status coverage, 64-orphan boundary,
rename/reorder/disable/remove/re-add lifecycle, persistence restart and
concurrent isolation are covered by:

- `TestCredentialDirectoryRejectsSeventeenFilesAtomically`;
- `TestLegacyMappingAndOrphanLimitsAreIndependent`;
- `TestLegacyMigrationAcceptsSixteenAndRejectsSeventeen`;
- `TestStageEStatsProjectionPublishesSixteenStableDevices`;
- `TestPersistenceV2WriteReadAndRestartNeverRestoresOnline`;
- `TestPersistenceRegistryRenameOrderDisableRemoveAndReadd`;
- `TestPersistenceSnapshotIsSelfConsistentDuringConcurrentUpdates`.

The frontend test runs the 16-device desktop/mobile selector, canonical hash,
localStorage fallback, disabled/removed fallback, hostile text boundaries,
per-page device isolation, zero-request switching, one manual fetch and one
automatic timer.

## Compatibility and rollback

Legacy TCP remains mapped explicitly and feeds the same state model.
`TestLegacyTCPAuthenticationMapsExplicitlyAndKeepsDuplicateRule`,
`TestCutoverOwnershipAcceptsOnlyActiveProtocolAndExpiresFailClosed`, the three
retained JSON-domain tests, and the 1 MiB wire limits cover compatibility.
There is no `device_json`, `lucky_json`, automatic username promotion or dual
writer.

Persistence-v1 fixtures are read without overwriting their source, are bound
only by explicit unambiguous mappings, retain unmatched/removed history as
bounded orphans, and never restore an online state. A production rollback must
use the protected pre-deployment snapshot and immutable prior images; no
production migration was executed here.

## Security and regression gates

- Candidate image stream scan found none of the generated tokens, token
  digests or private-key markers.
- Candidate Server logs contained hashed device references, outcomes, sizes
  and latency only; generated tokens, digests, request bodies, reported names,
  FQDN and forwarding address were absent.
- Public Stats contained no credential, token, ownership or orphan keys and no
  untrusted reported display name.
- Repository release-boundary checks reject environment/private-key material,
  credential patterns, browser secrets, Docker command fields and command
  endpoints.
- The endpoint and trusted-proxy interpretation default to disabled. Production
  exposure is permitted only through the exact reverse-proxy POST location.

The seven local CI-equivalent gates are contracts, Go (including race), Python,
frontend, Compose, image build/provenance and security. Their commands are
defined in `.github/workflows/ci.yml`; all must be repeated at the final merge
SHA.

## Residual risk and production work

Bearer tokens are replayable during their validity window. Verified HTTPS,
disabled TLS 0-RTT, per-device 256-bit tokens, current/next rotation, bounded
rate limits and redacted logs reduce but do not cryptographically eliminate
that risk. Sender-constrained credentials or mTLS at the reverse proxy are
future hardening, not 2.2 behavior.

HermesStatus 2.2 provides current monitoring only. It has no automatic
registration/discovery, command/control path, history database, alert engine,
multi-tenant isolation or RBAC. Production still requires a separately
approved registry, credential distribution/rotation, DNS/TLS ownership,
reverse-proxy/firewall configuration, persistence backup, canary migration and
rollback record.
