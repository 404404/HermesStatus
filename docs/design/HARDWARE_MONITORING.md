# Hardware Monitoring Design (2.3 Preview)

[中文](../zh-CN/HARDWARE_MONITORING.md) · [Documentation index](../README.md)

## Scope

Hardware monitoring is read-only, current-state observability for a configured
Client. It adds the Hardware view between Home and Docker without changing the
single `/json/stats.json` fetch path. The view contains:

1. CPU details and CPU use each occupy one desktop half. The CPU-use half has
   two columns for total, I/O wait, user, and system time; its percentage is
   shown only inside the bar. Vendor, family/model, topology, caches, idle,
   Nice, Steal, IRQ, and SoftIRQ are not rendered.
2. Memory details use the strict transposition of the prior vertical columns:
   physical/active-reclaimable, Swap/buffers-Slab, free/page-cache, and
   Swap-cache/dirty-writeback. The four-row, three-column grid keeps bounded,
   single-line values at normal 16:9 desktop widths.
3. System information: OS version, architecture, and kernel only.
4. Physical disks: model, capacity, temperature, SMART result, power-on hours,
   cumulative counters, and one row per associated partition or logical volume
   with its format, used/total capacity, and usage bar.

It does not control disks, change mounts, run repair commands, read directory
contents, expose raw SMART attributes, send serials/WWNs/UUIDs, or create a
disk-derived device identity.

## Storage model

The `hardware.storage` domain has separate bounded `physical_disks` and
`filesystems` arrays plus a summary, update time, stale flag, and sanitized
error. They are deliberately not one-to-one.

```text
Filesystem / logical volume
  → partition, LVM, MD RAID, device mapper, or Btrfs layer
  → zero or more physical disks
```

The Client derives the relationship from a bounded, cycle-safe block-device
graph built from read-only system metadata. It does not infer a relationship
from names such as `dm-0`, `md2`, or a vendor-specific mountpoint. This handles
ordinary partitions and generic LVM, MD RAID, and device-mapper stacks. A
multi-device Btrfs source does not prove every member through this graph, so its
backing relation remains unknown rather than incomplete. A filesystem row never
receives a fabricated single-disk temperature or SMART result.

The Server validates counts, string lengths, counters, statuses, paths, and
collection states before projection and persistence. Browser rendering escapes
all disk, model, mountpoint, filesystem, OS, and provenance strings.

CPU detail collection parses a fixed `lscpu --json` allowlist. When its
current-MHz field is absent, it uses a bounded average of numeric `cpu MHz`
lines from `/proc/cpuinfo`; raw command or proc-file output is not forwarded.
CPU use is calculated from two aggregate `/proc/stat` samples; `iowait`
remains distinct from idle. Memory uses a fixed `/proc/meminfo` allowlist.
These are observations, never device identity, and an unavailable optional
source does not invent a value.

## Physical SMART collection

`SMART_DEVICE` remains compatible with a single-disk installation. Device v2
adds a preferred explicit allowlist in `client-v2.json`:

```json
"hardware": {
  "smart_devices": [
    {"path": "/dev/sda", "type": null, "label": "data-disk-a"},
    {"path": "/dev/sdb", "type": "sat", "label": "data-disk-b"}
  ],
  "primary_smart_device": "/dev/sda"
}
```

`path` must be a validated `/dev/*` path already made visible to the Client
container. `type` is an optional bounded smartctl device type, not a command
argument fragment. `label` is collector configuration metadata and is not a
guaranteed persisted or UI field. The environment forms
`HERMESSTATUS_SMART_DEVICES` / `SMART_DEVICES` and
`HERMESSTATUS_PRIMARY_SMART_DEVICE` / `PRIMARY_SMART_DEVICE` are optional JSON
overrides. Precedence is CLI, environment, JSON file, then defaults. Legacy
`SMART_DEVICE` is the lowest-priority single-item form.

Each configured disk is collected independently. One failed, unsupported, or
permission-denied disk degrades hardware observation but does not discard the
other disks. `auto` remains a compatibility mode and can discover only devices
already visible and authorized to the container; it does not alter cgroups,
scan inaccessible host devices, or expand `/dev` permissions.

For legacy singular SMART compatibility:

- one valid physical disk supplies the singular fields;
- an explicit `primary_smart_device` supplies them for a multi-disk host;
- otherwise no arbitrary first disk is chosen. Detailed storage remains
  authoritative and the singular SMART result is an aggregate where possible.

## Minimum permissions

The base Client Compose file is non-privileged and maps no host block device.
For one or more confirmed disks, use an audited override that adds `SYS_RAWIO`,
replaces `devices:`, and maps every disk individually:

```yaml
cap_add:
  - SYS_RAWIO
devices: !override
  - /dev/sda:/dev/sda:r
  - /dev/sdb:/dev/sdb:r
environment: !override
  HERMESSTATUS_CONFIG_FILE: /etc/hermesstatus/client-v2.json
  SMART_DEVICE: ""
```

The matching JSON allowlist must contain only those paths. Do not use
`privileged`, mount the full `/dev` tree, add `SYS_ADMIN`, invoke a shell, or
grant a controller simply because a topology references it. If a platform
needs more access than this for SMART, document the limitation and stop rather
than expanding the trust boundary by default.

When an explicitly configured filesystem probe is on a known LVM or
device-mapper logical volume, map that one LV read-only alongside its already
authorized physical disk (for example,
`/dev/mapper/vgdata-root:/dev/mapper/vgdata-root:r`). This permits safe
topology resolution from the logical volume through its partition to the disk.
It does not authorize the full `/dev/mapper` directory, the device-mapper
control node, or any other block device; omit it when no configured probe uses
that LV.

## Filesystem probes

Container filesystem capacity is not automatically host filesystem capacity.
The Client samples only explicitly configured, read-only probe mounts:

```json
"filesystem_probes": [
  {"mountpoint": "/data", "probe_path": "/host-storage/data"}
]
```

```yaml
volumes:
  - /srv/example-data:/host-storage/data:ro
```

The display mountpoint (at most 512 characters) and container probe path must
be absolute, bounded, and free of parent traversal. The exact configured
mountpoint, including legal repeated whitespace, is preserved. The collector
uses `findmnt` and `statvfs` for metadata and capacity only. A bind-mount source
such as `/dev/sda1[/data]` is normalized to `/dev/sda1`; non-device sources are
omitted rather than exposing a remote endpoint. It does not recursively read
directories. Pseudo filesystems, invalid metadata, and inaccessible probes are unavailable data,
not zero usage and not a reason to mount the host root, enter a mount namespace,
use `nsenter`, or add `CAP_SYS_ADMIN`.

`available_bytes` uses `statvfs.f_bavail` (space usable by an unprivileged
writer), while `used_bytes` uses `f_blocks - f_bfree` so reserved filesystem
blocks are not incorrectly reported as free. The physical-disk table repeats a
disk for each safely resolved filesystem row; an unassociated disk gets a
single unavailable partition row rather than fabricated partition data.

## Home and Hardware semantics

Home uses physical-disk records for its temperature, SMART, cumulative I/O, and
power-on-hours cards. For multiple disks, the selected maximum or aggregate
states identify their device and do not represent filesystem logical I/O. A
single disk keeps the compact single-disk presentation. Hardware offers the
full safe inventory and permits horizontally scrollable tables on small screens.

System identity comes from safe host metadata such as a mounted `os-release`
file and `uname`; a DSM version source is optional and allowlist-parsed. When a
DSM source is absent, generic OS identity is used. No configuration file is
executed or sourced.

## Diagnostics and provenance

The Hardware page and read-only device diagnostics may show sanitized Device
identity/status, protocol, collection timestamps, system identity, per-item
collection state, and configured EasyTier expectation status. They never show
tokens, token digests, credential or registry paths, source address evidence,
private CA data, authentication headers, raw SMART output, or raw host config.

Build provenance is injected at image build time. Server build information and
optional selected-Client build information include bounded version, full Git
revision, and optional build time/protocol. Production images must not invoke
Git at runtime. Candidate qualification requires the full revision to match
the corresponding `org.opencontainers.image.revision` label.

Deployment environment is an allowlisted operator setting such as
`HERMESSTATUS_DEPLOYMENT_ENV=preview`; it is never inferred from a port. The
current independent 2.3 Preview staging deployment uses host port 21443 while
remaining isolated from 2.2 containers, config, state, images, networks, and
restart lifecycle.

## Qualification status

Real qualification covers the available GK50 hardware collection and its
single-disk compatibility path. Synthetic, secret-free fixtures cover generic
LVM, MD RAID, device mapper, Btrfs/EXT4, multi-disk SMART partial failure,
malicious strings, filesystem probe failure, and provenance validation.

Synology DSM layouts are prepared and synthetically qualified only. Real DSM
device names, storage layouts, version parsing, capacity, SMART, and memory
observations remain pending installation and read-only qualification on a real
Synology host. Synthetic examples never constitute real-device or dual-site
verification.
