# Canonical Compose contract

Mount the unified Client configuration read-only as:

Linux/GK50: /home/hermes/status/config/client-config.json:/run/secrets/hermesstatus/client-config.json:ro
Synology DSM: /volume1/docker/status/config/client-config.json:/run/secrets/hermesstatus/client-config.json:ro

Mount the Device v2 token separately as:

/etc/hermesstatus/secrets/device-token:/run/secrets/hermesstatus-device-token:ro

The Client also receives a private tmpfs:

/run/hermesstatus:size=4m,mode=0700,nosuid,nodev,noexec

Do not pass collector secrets through environment values or command arguments.
Server and Client images remain pinned by immutable release tag and digest in
the deployment process.
