# Architecture

[中文](zh-CN/ARCHITECTURE.md) · [Documentation index](README.md)

## Purpose

HermesStatus is a current-state dashboard for explicitly configured hosts. It
does not control hosts, containers, Hermes, Lucky, or EasyTier. The primary UI
has five views: Home, Hardware, Docker, Lucky, and EasyTier.

## Components and data flow

```text
Host OS / hwmon / SMART / explicit filesystem probes / Docker / Hermes / Lucky / EasyTier
                         ↓
                    Python Client
                         ↓
     Legacy TCP Agent  or  authenticated HTTPS device update
                         ↓
                      Go Server
                         ↓
          /json/stats.json · /api/health · WebUI
```

The Client collects host data and produces a structured extension with five
domains: `hardware`, `docker`, `hermes`, `lucky`, and `easytier`. Each domain
can be stale or unavailable without preventing the remaining domains from being
reported.

The Go Server validates the incoming update, keeps the latest accepted state,
persists selected state, and projects it as `/json/stats.json`. The browser
fetches that one document; switching between views does not create a separate
data request.

## Dashboard scope

The Home view presents device status, CPU, memory, disk capacity, EasyTier
remote-peer and traffic summaries, physical-disk temperature/SMART information,
Hermes profiles, and Lucky/EasyTier state and version summaries when configured.
EasyTier traffic uses one decimal place with automatic units and a single-line
receive / transmit / forwarded presentation. The Hermes Profile section header
shows the Agent version and profile count. Hardware follows Home and separates
system information, filesystems/volumes, and physical disks. Docker has a
separate container table; Lucky has its own configuration and service summaries;
EasyTier presents per-command collection-status cards followed by its read-only
network summary.

`hardware.storage.physical_disks` and `hardware.storage.filesystems` are
separate bounded collections. The Client builds a read-only block-device graph
to resolve ordinary partitions and generic LVM, MD RAID, device-mapper, and
Btrfs/EXT4 stacks to zero or more physical disk IDs. A filesystem never gains a
made-up temperature or SMART value. Only operator-configured physical SMART
devices and explicit read-only filesystem probe mounts are collected.

System identity reports sanitized distribution/release, kernel, architecture,
and source provenance. Build provenance is similarly read-only: the Server
reports build metadata and the selected Device may report Client build metadata.
Revision data is injected at build time and is expected to agree with the OCI
revision; no production image invokes Git at runtime. Environment is an
operator-supplied deployment label, not a conclusion drawn from a host port.

General host network throughput, cumulative host network traffic, and
carrier-specific or three-network latency probes are not HermesStatus dashboard
features and must not be documented as such, even though compatibility fields
may still exist in the legacy Agent protocol. This does not apply to the
separate EasyTier receive / transmit / forwarded counters.

## Ingestion modes

### Legacy TCP

The existing Agent opens a TCP connection, authenticates with its configured
username and password, receives monitor definitions, and sends updates. This
mode remains available for configured legacy devices.

### Device v2

Device v2 is disabled unless explicitly enabled. It accepts `POST
/api/v2/device-updates` only through the configured secure proxy boundary. A
device supplies an exact `X-HermesStatus-Device-ID`, a Bearer credential, and a
bounded JSON envelope. The Server matches the device against a startup-only
registry, validates the credential digest and identity, applies replay and
rate-limit checks, persists the accepted update, and returns sanitized monitor
definitions.

The registry supports at most 16 devices. Device discovery, browser-side
registration, remote control, RBAC, multi-tenancy, database history, WebSocket,
and SSE are outside the product boundary.

## 2.3 Preview EasyTier boundary

`2.3-preview` integrates 2.3 work and runs independent staging on 21443; it is
not a promotion to `2.0`. EasyTier reaches the Server only as a validated,
secret-free extension in the existing stats document. The browser uses the same
`/json/stats.json` fetch and selected device as the other views—no EasyTier
endpoint, timer, management channel, or identity mapping exists. Registry
expectations are comparison-only diagnostics, never authentication or identity.
