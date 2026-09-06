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
runtime UniFi identity + frozen Catalog bundle
        ↓
static capability projection + runtime observations
        ↓
normalized UniFi telemetry
        ↓
Device v2 → Server → /json/stats.json → UniFi tab
```

The Generic Collector V1 is shared by both profiles: `ubnt-systool cputemp`, aggregate `/proc/stat`, selected `/proc/meminfo`, `/proc/uptime`, and `/proc/loadavg`. CPU percentage uses two successful aggregate samples and excludes idle plus iowait. The first successful sample therefore reports `cpu_usage_pct=null` with `insufficient_delta`; it never reports a fabricated zero. Memory used is `MemTotal - MemAvailable`; only when `MemAvailable` is absent does the documented `MemFree + Buffers + Cached` fallback apply.

## Catalog consumer boundary

Static hardware capability is loaded from the vendored deterministic bundle in `clients/unifi_catalog/`, frozen from `404404/UniFi_Catalog` revision `486dacbcb8d0f14e5ee171ce99c6a5ffabc0fb62` with bundle SHA-256 `2251eddb656af89483a3497ca2fe46bf60339c3f96ae38b3390761d7f379a371` and checked by its SHA-256 manifest. The bundle is the authoritative source for neutral physical port labels, connector type, storage, power, PoE and qualified processor facts; HermesStatus does not maintain a parallel model table.

A collection profile is selected explicitly, but it is not a hardware identity and cannot unlock static capability. The controller `api_model`, `sysid`, and SSH model strings are runtime identifiers; only Catalog aliases marked `verified` may resolve a canonical SKU. Candidate aliases and unknown strings remain runtime observations and do not unlock static capability. The API output keeps runtime observations under `api`, while static capability is projected separately only after a verified runtime resolution.

Physical-port joins use the stable pair `(device_id, port_idx)`. Static port labels and capabilities are attached only to the matching device identity and physical index; missing runtime rows may receive static-only rows, and unknown models retain runtime rows without fabricated static fields. Power output distinguishes model-wide `absolute_max_poe_budget_w` from a particular `power_profiles[].poe_budget_w`; null remains unknown.

## Profiles and capability semantics

Profile selection is explicit (`udw` or `ucg-max`) and an unknown profile is rejected. Collection profiles express telemetry and diagnostic sources, while the normalized payload separately preserves `supported`, `present`, and `observed`. These are not interchangeable.

- Fan capability is never taken from the collection profile. The current frozen Catalog leaves UDW and UCG Max fan capability `unknown`; bounded `fanN` tachometer observations are retained with `supported=unknown` and `present=unknown` until the Catalog has an authoritative physical classification. A zero RPM observation remains `observed_zero_rpm`, never a failure.
- UCG Max has five thermal zones and `lm63` `fan1_input` is a verified hwmon RPM observation. The frozen Catalog is authoritative for its storage, power, PoE, port and processor capabilities; an unknown Catalog fan classification does not turn this runtime sensor into a physical-fan claim. UDW/UCG static capability is likewise never inferred from the profile name.

- The bounded UCG Max fan audit confirmed the repeatable read-only runtime source `linux.sensors_json` → `lm63` → `fan1_input` (RPM), including valid zero observations; companion temperature/alarm fields do not independently prove a physical fan. The Catalog therefore remains `unknown`, runtime observations are retained without a physical-fan claim, and no PWM or control sysfs path is read or written.

Raw thermal zones, hwmon detail, cputemp diagnostics, PWM, unmapped PSU sensors, and uncertain NVMe diagnostics remain out of the V1 UI and automatic health inference. Static storage and power capability are read from the verified runtime model's frozen Catalog projection; the collection profile remains responsible only for sources and formulas. Unknown runtime models retain bounded runtime observations while withholding static capability and do not make the whole UniFi domain stale. UDW filesystem usage uses the fixed read-only `unifi.udw.ssd_filesystem` source and `/ssd1`; `capacity_bytes` remains physical capacity while `filesystem_total_bytes` is the mounted filesystem total, and a missing mount is optional.

## Failure and freshness

SSH host-key, authentication, timeout, transport and parse failures preserve the last valid UniFi snapshot if one exists, mark UniFi `stale=true`, and expose a structured safe error. With no prior result, telemetry values are null rather than zero. Recovery clears stale/error on the next valid result. The Server treats this as a remote target status only: it never changes the Device v2 collector host identity, online state, hardware status, or unrelated domain health.

## Security boundary

The profile file cannot define a command. The code-side source registry has no arbitrary remote path or shell extension point. The transport uses a fixed bundled script, argv execution, bounded output and timeout, strict known-host verification, and protected file-backed keyboard-interactive authentication. No credentials, raw output, private endpoint details, controller configuration, or remote command result is persisted or displayed.

## Initial UI

The UniFi tab renders only profile, transport/freshness, CPU use, CPU temperature, memory, uptime, load, and bounded fan/PSU/storage capability state. Port tabs are keyed by authoritative device identity, sorted by numeric management IP, keep labels on one line, and wrap the tab row when needed; an explicit offline device is labelled with `（离线）`. It shares the browser's existing single stats document and refresh timer; it creates no separate polling endpoint.
