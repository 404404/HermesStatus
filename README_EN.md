# HermesStatus

[中文](README.md) · [English docs](docs/README.md) · [中文文档](docs/zh-CN/README.md)

HermesStatus is a self-hosted, multi-device status dashboard. The Python Client collects authorized host and local-service observations with least privilege; the Go Server validates, persists, and projects them; the browser renders Home, Hardware, Docker, Lucky, and EasyTier from one `/json/stats.json` document.

## Scope

- **Multi-device** — Device v2 uses an explicit Registry, per-device credential digest, and HTTPS ingestion. Registry `display_name` is the authoritative browser name; a Client hostname cannot replace it.
- **Host and hardware** — CPU, memory, uptime, OS, disks, SMART, temperatures, power-on hours, filesystems, and volumes. Devices and filesystems are explicitly authorized; the Client never scans host `/` or the whole `/dev` tree.
- **Docker** — read-only Docker-socket collection of bounded container summaries.
- **Hermes** — Profile summaries when installed. `not_installed` is a usable optional state, not a device failure.
- **Lucky** — loopback-only, read-only HTTP(S) collection of version, DDNS, web services, port forwards, and certificate summaries. Tokens are read only from protected files.
- **EasyTier** — read-only CLI and loopback RPC collection of node, peer, route, connector, traffic, and configured-vs-observed state. No remote peers, unobserved direct/relay paths, and unconfigured optional capabilities are not failures.

Network throughput, carrier probing, EasyTier management, remote command execution, auto-registration, history storage, and alerting are out of scope.

## Architecture

```text
authorized host inputs / Docker / Hermes / Lucky / EasyTier
                         ↓
                  Python Client
                         ↓
      Device v2 HTTPS or compatible Legacy TCP transport
                         ↓
                     Go Server
                         ↓
        /json/stats.json · /api/health · Web UI
```

The Server never reads a Docker socket, Lucky credential, EasyTier configuration, or raw CLI output. Inputs are allowlisted, bounded, typed, and secret-filtered at the Client boundary; the Server accepts only strict projections.

## Quick start

Server and Client have separate Compose configuration. Never commit production configuration, tokens, passwords, private CA material, or private addresses.

```bash
docker compose --env-file /secure/path/server.env -f docker-compose-server.yml up -d --build
docker compose --env-file /secure/path/client.env -f docker-compose-client.yml up -d --build
```

The default Web address is `http://127.0.0.1:8080/`; the status document is `/json/stats.json` and health is `/api/health`. Put production Device v2 only behind a fixed HTTPS reverse-proxy route and validate configuration before startup:

```bash
serverstatus --validate-device-config \
  --device-registry /absolute/path/devices.json \
  --device-credentials /absolute/path/credentials.d \
  --legacy-device-mapping /absolute/path/legacy-device-mapping.json
```

## Least-privilege hardware collection

Do not use `privileged`, `SYS_ADMIN`, all of `/dev`, or the host root directory for SMART or filesystem observation. Map each confirmed disk read-only, for example:

```yaml
cap_add: [SYS_RAWIO]
devices: [/dev/sda:/dev/sda:r]
environment:
  SMART_DEVICE: /dev/sda
```

Use `hardware.smart_devices` for multi-disk allowlists and `hardware.filesystem_probes` for fixed read-only filesystem probe paths. See the [Device configuration guide](docs/DEVICE_CONFIGURATION.md) and [hardware design](docs/design/HARDWARE_MONITORING.md).

## Known limitation

Some EasyTier 2.6.4 CLI output includes the local node in the peer list. Remote-peer summaries strictly exclude that row by own peer ID. Raw connection output can still vary by version and must not be over-interpreted as topology truth.

## Documentation and validation

- [Architecture](docs/ARCHITECTURE.md) · [Configuration](docs/CONFIGURATION.md) · [Deployment](docs/DEPLOYMENT.md)
- [Security](docs/SECURITY.md) · [Operations](docs/OPERATIONS.md) · [Development](docs/DEVELOPMENT.md)
- [Device configuration guide](docs/DEVICE_CONFIGURATION.md)
- [EasyTier monitoring](docs/design/EASYTIER_MONITORING.md) · [Hardware monitoring](docs/design/HARDWARE_MONITORING.md)

## License

[MIT License](LICENSE)
