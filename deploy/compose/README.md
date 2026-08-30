# Canonical Compose contract (2.5)

Published deployments must set `HERMESSTATUS_SERVER_TAG` and
`HERMESSTATUS_CLIENT_TAG` to the same immutable `2.5-<sha12>` candidate. Do
not use `2.5`, `latest`, or local qualification tags.

Mount the unified Client configuration read-only as:

Linux/GK50: /home/hermes/status/config/client-config.json:/run/secrets/hermesstatus/client-config.json:ro
Synology DSM: /volume1/docker/status/config/client-config.json:/run/secrets/hermesstatus/client-config.json:ro

Mount the Device v2 token separately as:

/etc/hermesstatus/secrets/device-token:/run/secrets/hermesstatus-device-token:ro

The Client also receives a private tmpfs:

/run/hermesstatus:size=4m,mode=0700,nosuid,nodev,noexec

Do not pass collector secrets through environment values or command arguments.
The operator must verify the candidate digest and OCI revision before creating
the container. The Synology template keeps `network_mode: host`, `pid: host`,
read-only rootfs, no-new-privileges, bounded tmpfs, Docker socket read-only,
DSM VERSION read-only, and only explicitly reviewed SMART/data-volume mounts.

Synology layout:

```text
/volume1/docker/status/
├── config/client-config.json
├── secrets/device-token
└── status/
```

The old 2.3 Client must be stopped before starting a 2.5 Client with the same
`device.id` and token. Keep the old image/container as rollback material until
the new candidate is accepted.
