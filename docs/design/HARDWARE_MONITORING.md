# Hardware Monitoring Design

The hardware domain is a bounded, fault-isolated observation pipeline. A failed
SMART command must not remove CPU, memory, filesystem, Docker or other hardware
observations.

## Sources and normalization

The Client collects CPU, memory, system identity, filesystems, physical disks
and SMART through fixed parsers. Hardware presentation distinguishes physical
disk properties (model, capacity, temperature, SMART and power-on hours) from
volumes/filesystems (mountpoint, source, type, usage and collection state).
This supports DSM RAID, mdraid, LVM and device-mapper without invented disk
ownership.

The overview selects the largest healthy configured filesystem. On DSM, a data
volume can therefore be selected naturally without hard-coding a volume name.

## SMART semantics

SMART devices are explicit allowlist entries. A native return-status result is
preferred. When native return status is unavailable but attributes and
thresholds provide a trustworthy fallback, the disk may be `passed` with
`partial` quality, `health_source: attribute_check` and a diagnostic warning.
That useful partial state does not by itself degrade the entire storage or
device state. A real failed health result remains a failure.

## Least privilege

Use explicit device mappings and `SYS_RAWIO` when required. Do not use
privileged mode, `SYS_ADMIN`, broad `/dev`, `/dev/sg*`, host root or arbitrary
paths. Filesystem observation uses configured narrow read-only probe mounts;
DSM version data, when necessary, is likewise a narrow read-only input.
