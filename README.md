# HermesStatus

HermesStatus is a single-host monitoring panel based on [cppla/ServerStatus](https://github.com/cppla/ServerStatus), tailored for a J4125 physical host running Hermes Agent profiles in containers.

The project keeps the original ServerStatus architecture: one server container and one client container. The UI, client-side collectors, and container deployment defaults are customized for a local Hermes host instead of a multi-node fleet.

## Features

- Single-host dashboard with the original `云监控` title.
- Top summary cards for CPU, memory, disk, running/total containers, and uptime.
- Hardware row for CPU temperature, disk current/highest/lowest temperature, SMART status, disk power-on hours, and disk written/read total.
- Hermes Agent profile table with service/API/gateway state, main model, token usage, job/session counts, and the detected Hermes Agent version.
- Profile details for auxiliary models, container mounts, and Mixture of Agents availability returned by the Hermes API.
- Docker container table modeled after `docker ps -a`.
- Config page reduced to reload config and restart service.
- 10-minute Hermes/Docker/SMART refresh loop with the last refresh time shown in the web UI.
- Config-driven Hermes profile names, paths, API endpoints, and config file locations.

## Runtime Layout

The recommended deployment directory on the target host is:

```text
/home/hermes/server-status
├── Dockerfile.client
├── Dockerfile.server
├── docker-compose-client.yml
├── docker-compose-server.yml
├── hermes-exporter.json
├── clients/
├── scripts/
├── server/
├── web/
└── hermes-status/
```

Hermes profile data is read from host paths configured in `hermes-exporter.json`. A typical J4125 layout is:

```text
/home/hermes/
├── hermes1/
├── hermes2/
├── hermes3/
├── workspaces/
├── outputs/
└── .hermes/profiles/
    ├── hermes1/config.yaml
    ├── hermes2/config.yaml
    └── hermes3/config.yaml
```

## Quick Start

Create or adjust `.env` in the project root:

```bash
SERVER=127.0.0.1
SERVERSTATUS_USER=s01
PASSWORD=USER_DEFAULT_PASSWORD
WEB_PORT=20443
ADMIN_TOKEN=change-this-token
HERMES_EXPORT_CONFIG_HOST=./hermes-exporter.json
HERMES_EXPORT_CONFIG=/app/hermes-exporter.json
HERMES_EXPORT_INTERVAL=600
SMART_DEVICE=/dev/sda
```

Start both containers:

```bash
docker compose -f docker-compose-server.yml -f docker-compose-client.yml up -d --build
```

Open the panel:

```text
http://<host-ip>:20443/
```

The server listens on `WEB_PORT` for the web UI and on `35601` for client reports. The client runs with host networking, host PID visibility, privileged device access, and read-only mounts for `/dev`, `/sys/class/hwmon`, the Docker socket, and `/home/hermes`.

## Hermes Export Config

`hermes-exporter.json` is the central place for custom paths and profile names:

```json
{
  "hermes_root": "/home/hermes",
  "status_dir": "/hermes/status",
  "profiles": [
    {
      "name": "hermes1",
      "profile_dir": "/home/hermes/hermes1",
      "config_path": "/home/hermes/.hermes/profiles/hermes1/config.yaml",
      "env_path": "/home/hermes/hermes1/.env",
      "api": {
        "enabled": true,
        "host": "127.0.0.1",
        "port": 8642
      }
    }
  ]
}
```

The same structure can be repeated for `hermes2`, `hermes3`, or any renamed profile. The client container mounts this file at `/app/hermes-exporter.json` by default.

## Data Sources

Hardware and Docker data are collected by `clients/client-psutil.py` and `scripts/export-hermes-status.py`.

| Panel data | Primary source |
| --- | --- |
| CPU usage, memory, disk, uptime | Host `psutil` metrics |
| CPU model | Host `lscpu --json`, with `/proc/cpuinfo` fallback |
| Host operating system | Read-only host `/etc/os-release` mount |
| CPU temperature | Host `/sys/class/hwmon` sensors |
| Disk SMART status | `sudo smartctl -x /dev/sda` |
| Disk temperature and lifetime stats | SMART Device Statistics GP Log |
| Running/total containers | Docker Engine socket |
| Container list and mounts | Docker Engine socket |
| Hermes service health | Profile API `GET /health` |
| Hermes sessions/jobs/runs/token usage | Profile API endpoints when enabled |
| Hermes gateway, main model, provider, auth refresh | `hermes -p <profile> status` |
| Hermes Agent version | Host `hermes --version` |
| Mixture of Agents | Profile API `GET /v1/toolsets` (`moa` / `mixture_of_agents`) |
| Auxiliary model and docker volume config | `/home/hermes/.hermes/profiles/<profile>/config.yaml` |

The CPU percentage is a live utilization metric from `psutil.cpu_percent()`. The static CPU model displayed below it is collected with `lscpu --json`, with `/proc/cpuinfo` as a fallback.

The Hermes API must stay bound to loopback by default. Do not expose `API_SERVER_HOST=0.0.0.0` directly. If remote access is required, use an authenticated reverse proxy, SSH tunnel, Tailscale, or Cloudflare Access.

## Hermes Config Fields

The exporter reads these sections from each profile config file:

- `terminal.docker_volumes`
- `auxiliary.vision`
- `auxiliary.web_extract`
- `auxiliary.compression`
- `auxiliary.skills_hub`
- `auxiliary.approval`
- `auxiliary.mcp`
- `auxiliary.title_generation`
- `auxiliary.triage_specifier`
- `auxiliary.kanban_decomposer`
- `auxiliary.profile_describer`
- `auxiliary.curator`

For auxiliary models, explicit provider/model settings are shown when `provider` is not `auto` and `model` is not empty. Entries with `provider: auto` and an empty `model` inherit the main model configuration.

## Operations

Show container state:

```bash
docker compose -f docker-compose-server.yml -f docker-compose-client.yml ps
```

Restart the stack:

```bash
docker compose -f docker-compose-server.yml -f docker-compose-client.yml up -d --build --force-recreate
```

Reload only the client collector:

```bash
docker compose -f docker-compose-server.yml -f docker-compose-client.yml up -d --build --force-recreate serverstatus-client
```

Inspect generated status files:

```bash
docker exec serverstatus-client ls -l /hermes/status
docker exec serverstatus-client python3 /app/export-hermes-status.py
```

## systemd

Create `/etc/systemd/system/hermes-status.service`:

```ini
[Unit]
Description=HermesStatus Docker Compose stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/hermes/server-status
RemainAfterExit=yes
ExecStart=/usr/bin/docker compose -f docker-compose-server.yml -f docker-compose-client.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose-server.yml -f docker-compose-client.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-status.service
```

## Validation

Run the local checks after changing collectors or config parsing:

```bash
python3 scripts/tests/test_hermes_config_summary.py
python3 scripts/tests/test_hermes_api_security.py
python3 scripts/tests/test_hermes_export_config.py
python3 -m py_compile \
  clients/client-psutil.py \
  scripts/export-hermes-status.py \
  scripts/hermes_config_summary.py
```

On a deployed host, also verify:

```bash
curl -fsSL http://127.0.0.1:20443/json/stats.json
sudo smartctl -x /dev/sda
docker ps -a
hermes -p hermes1 status
```

## Credits

HermesStatus is derived from `cppla/ServerStatus` and keeps the MIT license from the upstream project.
