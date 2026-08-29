# Deployment

Deploy Server and Clients from an immutable, reviewed revision.  Record the
full Git revision, image digest, OCI revision label, Compose project, ports,
mounts, state paths and restart count before changing a service.

## Normal sequence

1. Validate Server registry/credentials and Client configuration.
2. Build or pull exact Server and Client images from the same revision.
3. Back up state and non-secret configuration.
4. Recreate only the affected service.
5. Verify health, restart count, image digest/revision and accepted Device v2
   reports.
6. Verify `/health`, `/json/stats.json` and the relevant web pages.

Never use a mutable tag as the evidence for a qualification result.  A running
container's OCI revision label and digest must match the intended revision.

For the 2.5 release candidate, use the same immutable `2.5-<sha12>` tag for
Server and Client and verify the full OCI revision and digest before recreation.
Stable `2.3` remains unchanged; do not create or move a `2.5` or `latest` alias
during candidate qualification.

## Device v2 deployment

The Client must use its fixed JSON config file and read-only mounts for the
Device token and CA.  Do not inject legacy `SERVER`, `PORT`, user or password
variables into a Device v2 Client.  A failed preflight must not mutate a
container; retain an exact rollback target before recreation.

## Coexistence and rollback

Keep independent deployments isolated by Compose project, containers, networks,
state, configuration and credentials.  Do not stop or recreate an unrelated
stable service while qualifying another deployment.  On a real post-deploy
failure, roll back only to the exact state captured before the affected
recreation; do not delete persistent volumes as part of rollback.

## Validation after deployment

Confirm successful reports become fresh, restore behavior is stale until the
next accepted report, and the browser receives data through the existing stats
document.  Verify no secret is present in logs, process arguments, environment
output, stats projection or the UI.

## UniFi target deployment

UniFi is enabled only through a reviewed Device v2 JSON configuration and two
fixed read-only secret mounts: a credential file and a dedicated `known_hosts`
file. Validate both file type, ownership and mode before a Client recreation.
A container image can contain the profile library, but it must not contain
site-specific credentials, host keys, targets or raw discovery output. After
deployment, verify UniFi separately from host health: profile selection,
transport state, timestamp progression, and stale/error presentation are
expected evidence; a remote target failure must not be repaired by changing
Docker privileges or by recreating the remote console.

## Synology DSM manual cutover

Use the operator-ready Compose from `deploy/compose/client-synology.example.yml`
with the final immutable Client candidate tag. Prepare:

```text
/volume1/docker/status/
├── config/client-config.json
├── secrets/device-token
└── status/
```

The config is mounted read-only at
`/run/secrets/hermesstatus/client-config.json`; the Device v2 token remains a
separate read-only mount at `/run/secrets/hermesstatus-device-token`. Preserve
the existing SMART device and filesystem probe allowlists, DSM VERSION,
`network_mode: host`, `pid: host`, read-only rootfs, no-new-privileges, Docker
socket, and tmpfs settings. Add only individually reviewed block-device nodes.

Before cutover, capture the current 2.3 container, image digest, config and
status path. In DSM Container Manager, stop the old 2.3 Client, then recreate
the 2.5 Client with the exact candidate. Never run both clients concurrently
when they share a `device.id` and token. Verify Server health, fresh Device v2
reports and each enabled collector. For rollback, stop the 2.5 Client and
start the captured 2.3 container/image; do not delete its state or credentials
until acceptance is complete.
