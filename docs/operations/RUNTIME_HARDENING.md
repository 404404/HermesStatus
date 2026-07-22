# Runtime Permission Hardening

## Contents

- [Scope](#scope)
- [Permission matrix](#permission-matrix)
- [Implemented controls](#implemented-controls)
- [Accepted residual risks](#accepted-residual-risks)
- [Validation](#validation)

## Scope

This review covers the Go Server and the Python Client/Exporter runtime boundary. It does not add a Docker Socket proxy, container control operations, RBAC, or a new host collector. Each permission is retained unless repository code and deployment tests show that it can be narrowed without losing host, SMART, Docker, or Hermes telemetry.

## Permission matrix

| Permission or mount | Current purpose | Evidence in code | Necessity | Read-only | Removable | Production result |
|---|---|---|---|---|---|---|
| Client `privileged` | Allows SMART access through the host device tree | `smartctl -x` in `clients/host_collector.py` | Required by the current broad device model until a device/capability allowlist is proven | N/A | Not yet | Retained: disabling it changed fresh SMART status to `unknown`; restoring it returned `passed` |
| Client `pid: host` | Exposes host process and `/proc` metrics to the native client | `/proc/*` reads in `clients/client-linux.py`; process calls in `clients/client-psutil.py` | Required for current host process semantics | N/A | No | Retained |
| Client host network | Reaches host-loopback Hermes APIs and preserves native network probes | Hermes instance URLs and client probes | Required while Hermes APIs bind to loopback | N/A | No | Retained |
| Container user | Images currently run as root | SMART device access and Server port 80 | Required by current image/port model | N/A | Not in this change | Retained |
| `group_add` | Not configured | Compose inspection | Not used | N/A | Already absent | Absent |
| Client capabilities | Supplied by privileged mode | SMART/device access | Coupled to privileged mode | N/A | Not independently narrowed | Retained through privileged mode |
| Server capabilities | Server network and low-port behavior | Server listens on the configured HTTP and Agent ports | Full drop caused the published HTTP endpoint to refuse connections in the isolated production test | N/A | Not in this release | Retained after failed test |
| Explicit devices | Not configured; full `/dev` is mounted | SMART auto-discovery and `smartctl` | A portable allowlist is not yet proven | Read-only mount | Not yet | Retained |
| `/proc` | Inherited host view through `pid: host` | Native CPU, memory, disk, network, and process collection | Required | Kernel-managed | No | Retained |
| hwmon under `/sys` | CPU temperature | `collect_hwmon_temperatures()` | Required | Yes | No | Retained read-only |
| `/dev` | SMART device discovery and reads | `smart_candidates()` and `collect_smart()` | Required | Yes | Not yet | Retained read-only |
| Docker Socket | Lists all containers | `GET /containers/json?all=1` in `get_docker_containers()` | Required for Docker status | Bind is read-only but API authority is not | No | Retained risk |
| Hermes root | Profile config and CLI/API status inputs | `export-hermes-status.py` and `hermes_config_summary.py` | Required | Yes | No | Retained read-only |
| Client status directory | Atomic collector snapshots and Hermes summaries | `atomic_write_json()` and exporter `atomic_write()` | Required | No | No | Sole intended Client write bind |
| `no-new-privileges` | Prevents gaining privileges through exec | Runtime defense in depth | Compatible candidate | N/A | N/A | Passed for both containers with complete telemetry |
| Read-only rootfs | Prevents unplanned image-layer writes | Collectors write to the status bind; Server writes to `/app/data` | Compatible candidate | N/A | N/A | Passed for both containers; image-layer write probes failed as required |
| `/tmp` tmpfs | Supports safe transient runtime files with read-only rootfs | General runtime compatibility | Required with read-only rootfs | Writable, bounded | No | Passed with 16 MiB Server and 32 MiB Client limits; transient write probes succeeded |

## Implemented controls

- The Server enables `no-new-privileges` and uses a read-only root filesystem.
- The Server configuration bind is explicitly read-only. `/app/data` remains the only persistent Server write location.
- The Client enables `no-new-privileges` and uses a read-only root filesystem. Its status directory remains writable.
- Each container receives only a bounded `/tmp` tmpfs with `nosuid`, `nodev`, and `noexec`.
- The Server continues to have no Docker Socket, host devices, or Hermes directory mount.

## Accepted residual risks

The Client remains privileged and retains host PID, host network, read-only `/dev`, and the Docker Socket. The Socket bind's `ro` flag does not reduce Docker API authority; safety also depends on the collector's GET-only implementation. These controls are retained because current host process, SMART auto-discovery, Docker list, and loopback Hermes behavior must remain intact. Removal requires an isolated device/capability design, a documented observation window, and a tested rollback.

A complete Server capability drop was tested independently and rolled back after the published HTTP endpoint failed its `200` gate. The existing capability set remains an accepted residual risk until the listener/port model is narrowed with a dedicated rollback plan.

## Validation

Apply one control class at a time in the candidate environment. After every recreation verify host identity, CPU, memory, disk, SMART, temperature, power-on hours, sector totals, Docker counts/list, all three Hermes Profiles, health/detail, CLI fallback, jobs/sessions/token/config summary, Server health, and restart counts. Finish with force recreation and host-restart auto-start validation. Record failures as evidence for retaining the corresponding permission; do not weaken telemetry silently.

The production-isolated sequence completed in this order:

1. `no-new-privileges` passed for both containers with all HTTP and telemetry gates intact.
2. `cap_drop: [ALL]` on the Server caused the published HTTP endpoint to refuse connections and was rolled back immediately; the existing Server capability set is retained.
3. Read-only root filesystems plus bounded `/tmp` tmpfs mounts passed for both containers. Writes to the image layer failed, while `/tmp` remained writable.
4. Disabling Client privileged mode caused a fresh SMART result of `unknown`; Docker and Hermes remained available. Restoring privileged mode returned SMART to `passed`.
5. After a host reboot, both containers started automatically as healthy with restart count zero. Read-only rootfs, tmpfs, and `no-new-privileges` remained active, and the hardware, SMART, Docker, and Hermes gateways recovered. Hermes API listeners returned HTTP `200`; the dashboard's initial `unavailable` value was an early-boot collection result pending the next ten-minute refresh.

These observations establish compatibility for the implemented controls only. They are not a long-term performance, SLA, or unattended stability claim.

## Final status

The Runtime Hardening change was merged through PR #13. The post-merge baseline `0d953ac7b9842efcd888351d87426b8427465b5f` was rebuilt, deployed as a matching Server/Client pair, and passed the HTTP, telemetry, restart-count, OCI revision, read-only rootfs, tmpfs, and `no-new-privileges` gates. Final Closure images are rebuilt again from the later documentation merge SHA; this earlier baseline remains the tested rollback pair.
