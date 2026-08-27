# UniFi monitoring (V1)

UniFi monitoring is a profile-driven, read-only remote-observation domain in the HermesStatus 2.5 development line. It is intentionally limited to qualified UDW and UCG Max console models. It is not a UniFi controller integration, device discovery feature, inventory system, management API, remote shell, or configuration channel.

## Data model

```text
fixed symbolic source registry
        ↓
fixed one-session OpenSSH collection
        ↓
raw bounded observations
        ↓
administrator-selected model profile
        ↓
normalized UniFi telemetry
        ↓
Device v2 → Server → /json/stats.json → UniFi tab
```

The Generic Collector V1 is shared by both profiles: `ubnt-systool cputemp`, aggregate `/proc/stat`, selected `/proc/meminfo`, `/proc/uptime`, and `/proc/loadavg`. CPU percentage uses two successful aggregate samples and excludes idle plus iowait. The first successful sample therefore reports `cpu_usage_pct=null` with `insufficient_delta`; it never reports a fabricated zero. Memory used is `MemTotal - MemAvailable`; only when `MemAvailable` is absent does the documented `MemFree + Buffers + Cached` fallback apply.

## Profiles and capability semantics

Profile selection is explicit (`udw` or `ucg-max`) and an unknown profile is rejected. Profiles express model capability, while the normalized payload separately preserves `supported`, `present`, and `observed`. These are not interchangeable.

- UDW exposes four controller fan channels, but only `fan1` and `fan2` are physically populated in the qualified profile. `fan3`/`fan4` observations are ignored as `profile_not_populated`; zero does not become failure. Two PSU slots are capability metadata; current slot presence is dynamic/unknown until a proven sensor mapping exists.
- UCG Max has five thermal zones and `lm63` diagnostics, but their physical mapping is unknown. `fan1=0` remains an `observed_zero_rpm` value with physical presence unknown. NVMe not observed is not evidence of an absent physical NVMe device.

Raw thermal zones, hwmon detail, cputemp diagnostics, PWM, unmapped PSU sensors, and uncertain NVMe diagnostics remain out of V1 UI and automatic health inference.

## Failure and freshness

SSH host-key, authentication, timeout, transport and parse failures preserve the last valid UniFi snapshot if one exists, mark UniFi `stale=true`, and expose a structured safe error. With no prior result, telemetry values are null rather than zero. Recovery clears stale/error on the next valid result. The Server treats this as a remote target status only: it never changes the Device v2 collector host identity, online state, hardware status, or unrelated domain health.

## Security boundary

The profile file cannot define a command. The code-side source registry has no arbitrary remote path or shell extension point. The transport uses a fixed bundled script, argv execution, bounded output and timeout, strict known-host verification, and protected file-backed keyboard-interactive authentication. No credentials, raw output, private endpoint details, controller configuration, or remote command result is persisted or displayed.

## Initial UI

The UniFi tab renders only profile, transport/freshness, CPU use, CPU temperature, memory, uptime, load, and bounded fan/PSU/storage capability state. It shares the browser's existing single stats document and refresh timer; it creates no separate polling endpoint.
