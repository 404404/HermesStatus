# HermesStatus 2.2 Manual Device Registration

HermesStatus 2.2 registers devices only from startup configuration. It does
not auto-register from a hostname, FQDN, IP address, credential, legacy
username, persistence record, browser action, API request, or discovery
protocol.

## Configuration files

The server uses the existing configuration variables below. Do not introduce
aliases for the same files.

| Variable | Container path | Purpose |
| --- | --- | --- |
| `DEVICE_REGISTRY_PATH` | `/etc/hermesstatus/devices.json` | authoritative device registry |
| `HERMESSTATUS_DEVICE_CREDENTIALS_DIR` | `/etc/hermesstatus/credentials.d` | one digest-only JSON file per v2 device |
| `LEGACY_DEVICE_MAPPING_PATH` | `/etc/hermesstatus/legacy-device-mapping.json` | explicit legacy username-to-device mapping |
| `PERSISTENCE_PATH` | `/var/lib/hermesstatus/state-v2.json` | writable v2 runtime persistence |

Registry and mapping paths must be absolute, normalized, ordinary non-symlink
files. The credential directory must be an absolute, normalized,
non-symlink directory containing only `<device_id>.json` ordinary files.
Mount the three configuration inputs read-only. Persistence is separate and
writable.

An explicit relative `PERSISTENCE_PATH`/`--state` is resolved against the
configuration document directory; parent traversal components are rejected.
If the state path is omitted, the Server first canonicalizes the Stats path
against that same directory and derives `<stats-path>.state-v2`. Primary and
backup then use that fixed absolute directory. Existing symlink components are
rejected.

The registry is authoritative for device ID, display name, expected FQDN,
enabled state, ordering, groups, tags, time thresholds, default device and
ingestion ownership. Client-reported name, hostname and FQDN are observations
only. The server reads these files at startup; there is no watcher and the
server never modifies them.

Synthetic, validator-compatible files are in
[`config/examples`](../../config/examples/).

## Validate without starting the server

Run the server binary with the same read-only mounts and environment that will
be used at startup:

```sh
serverstatus --validate-device-config
```

The command validates the registry, 16-device limit, default and ownership
rules, credential directory, current/next slots, required active credentials,
legacy mappings and their cross-file relationships. It does not create
listeners, nodes, stats or persistence; it performs no writes and no network
access.

Success prints only counts and the safe default `device_id`. Failure exits 2
and prints only a fixed error code and non-sensitive field location. It never
prints file contents, absolute paths, tokens, digests, FQDNs or registry
documents.

Example validation from the repository root:

```sh
serverstatus \
  --device-registry "$PWD/config/examples/device-registry.example.json" \
  --device-credentials "$PWD/config/examples/credentials.d" \
  --legacy-device-mapping "$PWD/config/examples/legacy-device-mapping.example.json" \
  --validate-device-config
```

## Provision a v2 credential offline

Create operator-owned directories first, then call the helper with explicit
absolute targets and an explicit validity window:

```sh
python3 scripts/provision_device_credential.py compute-01 \
  --client-token-file /secure/client/compute-01.token \
  --server-credential-file /secure/server/credentials.d/compute-01.json \
  --not-before 2026-07-29T00:00:00Z \
  --not-after 2027-07-29T00:00:00Z
```

The helper obtains 32 bytes from the operating-system CSPRNG and writes a
43-character unpadded base64url token only to the client file. The server file
contains only its SHA-256 digest. Both writes are atomic and mode `0600`;
existing targets are rejected by default. The helper does not access the
network, edit the registry or Compose, restart a service, or log the token.

Use `--dry-run` to validate parameters and targets without generating a token
or writing files. Use `--overwrite` only after checking the named ordinary
files. Symlinks and directories are always rejected.

To prepare rotation without removing `current`, use a distinct client token
target and merge a `next` slot into the existing server record:

```sh
python3 scripts/provision_device_credential.py compute-01 \
  --client-token-file /secure/client/compute-01.next.token \
  --server-credential-file /secure/server/credentials.d/compute-01.json \
  --slot next \
  --not-before 2026-08-01T00:00:00Z \
  --not-after 2027-08-01T00:00:00Z \
  --overwrite
```

Deploy the updated digest record first, validate it, restart the startup-only
server configuration, and then deploy the matching client token. Remove the
old `current` slot only in a later explicit change after the new slot is
confirmed.

## Manual lifecycle

1. Provision the credential offline.
2. Add the device to the registry manually, keeping `display_name` and
   ownership explicit.
3. Mount the digest record on the server and the token file on only that
   client.
4. Run `--validate-device-config`.
5. Restart the server to load the new startup-only registry.
6. Start the client and verify its isolated Home, Docker, Hermes and Lucky
   data.

For a rename, edit only registry `display_name`, validate and restart. To stop
ingestion while retaining history, set `enabled=false`. To remove a device,
disable it first, validate the retained state, then remove its registry,
credential and mapping entries together in a later reviewed change.

The reverse-proxy example exposes only exact
`POST /api/v2/device-updates`, permits TLS 1.2/1.3 with TLS 1.3 early data
disabled, caps request and header sizes, uses bounded timeouts, disables
caching, and does not log authorization or bodies. Keep the backend port on an
internal network so the authenticated proxy boundary cannot be bypassed.
