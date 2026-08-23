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
