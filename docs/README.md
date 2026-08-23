# HermesStatus documentation

[中文文档](zh-CN/README.md)

This set documents the current `2.0` product line. It describes deployed behavior, strict trust boundaries, and known limitations; it does not document a promotion workflow or a port as a product environment.

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

Keep the English and Chinese documents semantically synchronized in the same documentation change.
