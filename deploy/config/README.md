# Unified Client configuration

The Client reads one JSON document at HERMESSTATUS_CONFIG_FILE (canonical
container path /run/secrets/hermesstatus/client-config.json). The document
uses schema_version: 1, rejects unknown fields, and names every collector
explicitly. The Device v2 token remains a separate read-only mount at
/run/secrets/hermesstatus-device-token.

Collector credentials may be present only in the root-owned configuration file.
At startup the Client validates the document and materializes Lucky and UniFi
credentials into private ephemeral files below /run/hermesstatus; no secret is
placed in an environment variable, argument list, status payload, or log.

Profiles contain symbolic, fixed sources only. Arbitrary commands, paths,
containers, RPC endpoints, and remote hosts are rejected. Keep the config file
root:root and mode 0600 and mount it read-only. Use a tmpfs at /run/hermesstatus
(mode 0700, nosuid,nodev,noexec) for materialized credentials.

The legacy client-v2.json schema remains accepted for rollback compatibility;
new deployments should use this unified document.

Canonical host locations:

- GK50/Linux: `/home/hermes/status/config/client-config.json`
- Synology DSM: `/volume1/docker/status/config/client-config.json`

Both locations mount read-only at `/run/secrets/hermesstatus/client-config.json`.
