# HermesStatus 2.0

[中文](README.md) · [English docs](docs/README.md) · [中文文档](docs/zh-CN/README.md)

HermesStatus is a self-hosted current-state dashboard. The Go Server receives
Client updates and serves the WebUI and status API. The Python Client collects
host, hardware/SMART, Docker, Hermes, and optional Lucky data.

## Current capabilities

- Home: device state, CPU, memory, disk capacity, host/CPU identity,
  temperature, and SMART.
- Docker: container counts, names, images, state, and port summaries.
- Hermes: configured profiles with gateway, runtime, model/provider, and usage
  snapshots.
- Lucky: version, DDNS, web service, forwarding, and certificate summaries when
  explicitly enabled.
- Legacy TCP Agents and optional Device v2 ingestion.

Network traffic, network throughput, and carrier-specific or three-network
latency probes are not HermesStatus dashboard features.

## Architecture

```text
Host / hwmon / SMART / Docker / Hermes / Lucky
                       ↓
                  Python Client
                       ↓
      Legacy TCP Agent or authenticated HTTPS Device v2 update
                       ↓
                    Go Server
                       ↓
        /json/stats.json · /api/health · WebUI
```

The browser reads only `/json/stats.json`. The Server does not mount the Docker
socket or read Hermes/Lucky secrets; that high-trust work belongs to the Client.

## Local start

```bash
docker compose --env-file /secure/path/server.env \
  -f docker-compose-server.yml up -d --build

docker compose --env-file /secure/path/client.env \
  -f docker-compose-client.yml up -d --build
```

The default Server address is `http://127.0.0.1:8080/`. Health is at
`/api/health`, status is `/json/stats.json`, and Legacy Agent TCP listens on
`35601`. Prefer `SERVERSTATUS_USER`; `USER` exists only for compatibility.

## Minimum SMART permissions

Do not use `privileged` or mount the full `/dev` tree solely to collect SMART.
For a confirmed `/dev/sda` disk:

```yaml
cap_add:
  - SYS_RAWIO
devices:
  - /dev/sda:/dev/sda:r
environment:
  SMART_DEVICE: /dev/sda
```

This block replaces, rather than supplements, the legacy broad entries in
`docker-compose-client.yml`: set `CLIENT_PRIVILEGED=false` and remove its
`/dev:/dev:ro` volume before adding the capability and single-device mapping.
Keeping those defaults is not a minimum-permission deployment.

Keep the read-only root filesystem and `no-new-privileges`. Other disks, RAID,
or NVMe controllers need an explicit, validated device grant.

## Device v2

Device v2 is disabled by default. It needs a read-only registry, one
SHA-256-digest credential document per device, a Legacy mapping when needed,
and a writable runtime-state file. Expose `POST /api/v2/device-updates` only
behind a fixed HTTPS reverse-proxy route.

```bash
serverstatus --validate-device-config \
  --device-registry /absolute/path/devices.json \
  --device-credentials /absolute/path/credentials.d \
  --legacy-device-mapping /absolute/path/legacy-device-mapping.json
```

## Documentation and validation

- [Architecture](docs/ARCHITECTURE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Security](docs/SECURITY.md)
- [Operations](docs/OPERATIONS.md)
- [Development and testing](docs/DEVELOPMENT.md)

```bash
(cd server && go test ./...)
(cd clients && python3 -m unittest discover)
(cd scripts/tests && python3 -m unittest discover)
```

Never commit real tokens, passwords, credentials, private addresses, or
production configuration.

## License

[MIT License](LICENSE)
