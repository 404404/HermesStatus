# Unified Client configuration (2.5)

2.5 Clients may use the strict JSON document described by
schemas/client-config.schema.json. Set HERMESSTATUS_CONFIG_FILE to the
read-only mount /run/secrets/hermesstatus/client-config.json; the Device v2
token remains a separate mount at /run/secrets/hermesstatus-device-token.

The document has schema_version: 1, explicit server, device, optional
collection, and all eight collector sections (`hardware`, `filesystem`, `smart`,
`docker`, `hermes`, `lucky`, `easytier`, `unifi`). Unknown fields and unknown
collector sources fail closed. Collector-specific secrets can be embedded in
the root-owned (0600) document, but the Client immediately materializes them
under /run/hermesstatus (tmpfs, 0700, noexec) and never places them in env,
argv, logs, or Device v2.

For UniFi, `profile`, target address, username, credential file, known_hosts
file, API URL/key and TLS fingerprint are conditional fields. They are accepted
only when the UniFi collector is enabled and are validated against fixed
loopback/API/SSH policies; the profile cannot inject commands or arbitrary
paths. Lucky and EasyTier credentials follow the same file-only rule, while the
Device v2 token remains a separate trust-boundary mount.

Use only symbolic, fixed source IDs and fixed loopback RPC/URL policies. Keep
the legacy client-v2.json schema available for rollback; migration should
retain a copy of the old Compose/config and verify equivalent Device v2 cycles
before removing it.
