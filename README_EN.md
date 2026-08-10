# HermesStatus 2.3 Preview

[中文](README.md) · [English docs](docs/README.md) · [中文文档](docs/zh-CN/README.md)

HermesStatus is a self-hosted current-state dashboard. The Go Server receives
Client updates and serves the WebUI and status API. The Python Client collects
host, hardware/SMART, Docker, Hermes, optional Lucky data, and an optional
EasyTier health projection.

## Current capabilities

- Device names are configuration-driven by the Device Registry and never
  accept a Client hostname override. Production names should be stable (for
  example, `GK50`) and must not include Preview or temporary-environment text;
  each Client keeps its endpoint IP and port in a separate Client configuration
  file.
- Home first shows CPU, memory, disk capacity, EasyTier remote-peer counts, and
  EasyTier traffic. The hardware area shows SMART, read/write volume, power-on
  hours, system uptime, physical-host OS, Docker, Lucky, and EasyTier
  state/version. State and version use a compact “Normal (version)” form, and
  EasyTier traffic uses one decimal place in a single-line receive / transmit /
  forwarded layout with automatic B/KB/MB/GB unit scaling.
- Docker: container counts, names, images, state, and port summaries.
- Home also includes configured Hermes profiles with gateway, runtime,
  model/provider, and usage snapshots. Its section header shows the shared
  Agent version and profile count (for example, `Agent version: 0.19.0, 3 profiles`).
- Lucky: version, DDNS, web service, forwarding, and certificate summaries when
  explicitly enabled.
- EasyTier: an opt-in, strict read-only loopback-RPC projection. Each
  collection command is shown first as an individual status card, followed by
  Node, Configured vs Observed, Peer, Route, Connector, and traffic views.
  With zero remote peers, direct, relay, and IPv6 UDP Direct are
  not-observable—not misleading zero or false values.
- Legacy TCP Agents and optional Device v2 ingestion.

Network traffic, network throughput, and carrier-specific or three-network
latency probes are not HermesStatus dashboard features.

## Architecture

```text
Host / hwmon / SMART / Docker / Hermes / Lucky / EasyTier
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
EasyTier CLI is likewise Client-only; neither the Server nor browser sees its
configuration, credentials, RPC portal, or raw CLI output.

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
- [EasyTier 2.3 design](docs/design/EASYTIER_MONITORING.md)
- [Device configuration guide](docs/DEVICE_CONFIGURATION.md)

```bash
(cd server && go test ./...)
(cd clients && python3 -m unittest discover)
(cd scripts/tests && python3 -m unittest discover)
```

`2.3-preview` is the sole 2.3 integration and 21443 staging branch; it is not
automatically promoted to `2.0`. Only real GK50 zero-peer collection is
currently qualified. Real Synology dual-site, IPv6 UDP Direct, TCP fallback,
192.168.88.0/24, and real Direct/Relay behavior remain pending. Synthetic
fixtures qualify preview states only and are never real-network verification.

Never commit real tokens, passwords, credentials, private addresses, or
production configuration.

## License

[MIT License](LICENSE)
