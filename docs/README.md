# HermesStatus documentation

[中文文档](zh-CN/README.md)

This documentation set describes the 2.3 Preview code maintained on
`2.3-preview`. It is an integration and 21443 staging branch, not an automatic
promotion path to `2.0`; real two-site qualification remains required.

| Document | Purpose |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | Components, data flow, dashboard scope, storage separation, and non-goals. |
| [Configuration](CONFIGURATION.md) | Server, Client, hardware/SMART, filesystem probes, Hermes, Lucky, and multi-device configuration. |
| [Device configuration guide](DEVICE_CONFIGURATION.md) | Device name authority, endpoint fields, safe hardware paths, Compose mounts, and examples. |
| [Deployment](DEPLOYMENT.md) | Local Compose, production deployment, 21443 Preview, and the hardware device boundary. |
| [Security](SECURITY.md) | Trust boundaries, credentials, and safe exposure rules. |
| [Operations](OPERATIONS.md) | Health checks, stale data, backup, upgrade, and troubleshooting. |
| [Development](DEVELOPMENT.md) | Local validation and pull-request workflow. |
| [EasyTier monitoring design](design/EASYTIER_MONITORING.md) | Read-only data boundary, states, fixtures, and qualification. |
| [Hardware monitoring design](design/HARDWARE_MONITORING.md) | Physical disks, filesystems, safe probes, provenance, diagnostics, and qualification status. |

The Chinese documents are translations of this document set. Keep changes to
both languages in the same pull request.
