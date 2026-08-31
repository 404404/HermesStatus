# UniFi monitoring (V1)

UniFi monitoring is a profile-driven, read-only remote-observation domain in the HermesStatus 2.6 development line. It is intentionally limited to qualified UDW and UCG Max console models. It is not a UniFi controller integration, device discovery feature, inventory system, management API, remote shell, or configuration channel.

## Data model

```text
fixed symbolic source registry
        ↓
fixed one-session OpenSSH collection
        ↓
raw bounded observations
        ↓
administrator-selected collection profile + frozen Catalog bundle
        ↓
static capability projection + runtime observations
        ↓
normalized UniFi telemetry
        ↓
Device v2 → Server → /json/stats.json → UniFi tab
```

The Generic Collector V1 is shared by both profiles: `ubnt-systool cputemp`, aggregate `/proc/stat`, selected `/proc/meminfo`, `/proc/uptime`, and `/proc/loadavg`. CPU percentage uses two successful aggregate samples and excludes idle plus iowait. The first successful sample therefore reports `cpu_usage_pct=null` with `insufficient_delta`; it never reports a fabricated zero. Memory used is `MemTotal - MemAvailable`; only when `MemAvailable` is absent does the documented `MemFree + Buffers + Cached` fallback apply.

## Catalog consumer boundary

Static hardware capability is loaded from the vendored deterministic bundle in `clients/unifi_catalog/`, frozen from `404404/UniFi_Catalog` revision `2a8991933b5f4a323c27c30d9370ec3836d749b4` with bundle SHA-256 `52b4313e9c619f13af7ba64a19fb69d2259092586eed0af4f8e698f32e577791` and checked by its SHA-256 manifest. The bundle is the authoritative source for physical ports, storage, power, PoE and qualified processor facts; HermesStatus does not maintain a parallel model table.

A canonical SKU is selected only by an explicit administrator profile. Controller `api_model`, `sysid`, and SSH model strings are runtime identifiers; only Catalog aliases marked `verified` may resolve a model. Candidate aliases and unknown strings remain runtime observations and do not unlock static capability. The API output keeps runtime observations under `api`, while static capability is projected separately.

Physical-port joins use the stable pair `(device_id, port_idx)`. Static port labels and capabilities are attached only to the matching device identity and physical index; missing runtime rows may receive static-only rows, and unknown models retain runtime rows without fabricated static fields. Power output distinguishes model-wide `absolute_max_poe_budget_w` from a particular `power_profiles[].poe_budget_w`; null remains unknown.

## Profiles and capability semantics

Profile selection is explicit (`udw` or `ucg-max`) and an unknown profile is rejected. Collection profiles express telemetry and diagnostic sources, while the normalized payload separately preserves `supported`, `present`, and `observed`. These are not interchangeable.

- UDW exposes four controller fan channels, but only `fan1` and `fan2` are physically populated in the qualified profile. `fan3`/`fan4` observations are ignored as `profile_not_populated`; zero does not become failure. Two PSU slots are capability metadata; current slot presence is dynamic/unknown until a proven sensor mapping exists.
- UCG Max has five thermal zones; `lm63` `fan1_input` is a verified hwmon RPM observation. Physical fan presence is qualified by FCC ID `SWX-UCGM`, “Ubiquiti UCG-Max Internal Photos”, Document ID `7461768`, whose internal image shows a blower adjacent to the SSD assembly. The profile therefore marks `fan1` as `supported=true`, `present=present`; missing input is `not_observed`, a positive value is `observed`, and zero is `observed_zero_rpm`, never a failure. The profile declares NVMe capability and does not declare SATA SSD or TF capability; NVMe not observed is not evidence of an absent physical NVMe device.

Raw thermal zones, hwmon detail, cputemp diagnostics, PWM, unmapped PSU sensors, and uncertain NVMe diagnostics remain out of the V1 UI and automatic health inference. Static storage and power capability are read from the frozen Catalog projection; the collection profile remains responsible for sources and formulas: UDW exposes TF and internal SATA SSD capability plus PSU details; non-UDW models with no observable PSU capability hide the complete power section. UDW filesystem usage uses the fixed read-only `unifi.udw.ssd_filesystem` source and `/ssd1`; `capacity_bytes` remains physical capacity while `filesystem_total_bytes` is the mounted filesystem total, and a missing mount is optional.

## Failure and freshness

SSH host-key, authentication, timeout, transport and parse failures preserve the last valid UniFi snapshot if one exists, mark UniFi `stale=true`, and expose a structured safe error. With no prior result, telemetry values are null rather than zero. Recovery clears stale/error on the next valid result. The Server treats this as a remote target status only: it never changes the Device v2 collector host identity, online state, hardware status, or unrelated domain health.

## Security boundary

The profile file cannot define a command. The code-side source registry has no arbitrary remote path or shell extension point. The transport uses a fixed bundled script, argv execution, bounded output and timeout, strict known-host verification, and protected file-backed keyboard-interactive authentication. No credentials, raw output, private endpoint details, controller configuration, or remote command result is persisted or displayed.

## Initial UI

The UniFi tab renders only profile, transport/freshness, CPU use, CPU temperature, memory, uptime, load, and bounded fan/PSU/storage capability state. Port tabs are keyed by authoritative device identity, sorted by numeric management IP, keep labels on one line, and wrap the tab row when needed; an explicit offline device is labelled with `（离线）`. It shares the browser's existing single stats document and refresh timer; it creates no separate polling endpoint.
