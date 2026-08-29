# HermesStatus documentation

[中文文档](zh-CN/README.md)

This set documents the current `2.5` development line. It describes deployed
behavior, strict trust boundaries, candidate deployment and known limitations;
the release candidate workflow does not itself promote Stable 2.3.

| Document | Purpose |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | Components, data flow, ownership, and product boundaries. |
| [Configuration](CONFIGURATION.md) | Server, Client, Device v2, hardware, Lucky, and EasyTier settings. |
| [Device configuration guide](DEVICE_CONFIGURATION.md) | Registry identity, credential files, Client config, and safe mounts. |
| [Deployment](DEPLOYMENT.md) | Compose deployment, upgrade, verification, and rollback. |
| [Security](SECURITY.md) | Trust boundaries, credentials, transport, and least privilege. |
| [Operations](OPERATIONS.md) | Freshness, health interpretation, backups, and troubleshooting. |
| [Development](DEVELOPMENT.md) | Test gates and pull-request workflow. |
| [EasyTier monitoring](design/EASYTIER_MONITORING.md) | Read-only model, source boundaries, and semantics. |
| [Hardware monitoring](design/HARDWARE_MONITORING.md) | SMART, filesystems, storage topology, and diagnostic semantics. |
| [UniFi monitoring](design/UNIFI_MONITORING.md) | Profile-driven read-only SSH telemetry for qualified UniFi console models. |

Keep the English and Chinese documents semantically synchronized in the same documentation change.
