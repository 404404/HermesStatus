#!/usr/bin/env python3
"""Collect the Release A host extensions without blocking native updates."""

import copy
import datetime
import glob
import json
import os
import re
import shlex
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import PurePosixPath

from lucky_collector import collector_from_environment, not_configured_lucky
from easytier_collector import collector_from_environment as easytier_collector_from_environment
from easytier_collector import not_configured_easytier
from unifi_collector import not_configured_unifi, not_collected_unifi


EXTENSION_VERSION = "1.0-draft"
REDACTED_VALUE = "[redacted]"

MAX_CPU_MODEL_LENGTH = 128
MAX_CPU_VENDOR_LENGTH = 128
MAX_CPU_TEXT_LENGTH = 128
MAX_TEMPERATURE_SOURCE_LENGTH = 128
MAX_DISK_DEVICE_LENGTH = 128
MAX_DISK_SMART_SOURCE_LENGTH = 64
MAX_DISK_MODEL_LENGTH = 256
# This value is a wire contract shared with the Go Server.  Keeping the client
# cap at the server's limit ensures a legitimate local probe cannot make the
# complete hardware domain fail strict validation merely because its source is
# longer than the projection accepts.
MAX_FILESYSTEM_SOURCE_LENGTH = 256
MAX_MOUNTPOINT_LENGTH = 512
MAX_FILESYSTEM_TYPE_LENGTH = 64
MAX_SYSTEM_IDENTITY_TEXT_LENGTH = 256
MAX_DOCKER_CONTAINERS = 256
MAX_DOCKER_COUNT = 100000
MAX_SAFE_INTEGER = 9007199254740991
MAX_DOCKER_NAME_LENGTH = 256
MAX_DOCKER_STATUS_LENGTH = 128
MAX_DOCKER_IMAGE_LENGTH = 256
MAX_DOCKER_PORTS_LENGTH = 512
MAX_HERMES_PROFILES = 64
MAX_PHYSICAL_DISKS = 64
MAX_FILESYSTEMS = 128
MAX_FILESYSTEM_BACKING_DISKS = 16
MAX_BLOCK_GRAPH_DEPTH = 16
MAX_BLOCK_GRAPH_NODES = 256

# The hardware document deliberately keeps CPU and memory facts typed and
# bounded. It must never forward arbitrary command output such as the full
# ``lscpu`` or ``/proc/meminfo`` document.
CPU_USAGE_SAMPLE_SECONDS = 0.10
MAX_CPUINFO_LINES = 4096
_CPU_LSCPU_TEXT_FIELDS = {
    "architecture": "architecture",
    "vendor id": "vendor",
    "cpu family": "family",
    "model": "model_id",
    "stepping": "stepping",
    "virtualization": "virtualization",
    "l1d cache": "l1d_cache",
    "l1i cache": "l1i_cache",
    "l2 cache": "l2_cache",
    "l3 cache": "l3_cache",
}
_CPU_LSCPU_INTEGER_FIELDS = {
    "cpu(s)": "logical_cpus",
    "socket(s)": "sockets",
    "core(s) per socket": "cores_per_socket",
    "thread(s) per core": "threads_per_core",
}
_CPU_LSCPU_FLOAT_FIELDS = {
    "cpu max mhz": "max_mhz",
    "cpu min mhz": "min_mhz",
    "cpu mhz": "current_mhz",
}
_CPU_INSTRUCTION_SET_FLAGS = (
    ("sse", "SSE"), ("sse2", "SSE2"), ("sse4_1", "SSE4.1"),
    ("sse4_2", "SSE4.2"), ("aes", "AES"), ("avx", "AVX"),
    ("avx2", "AVX2"), ("avx512f", "AVX-512"), ("fma", "FMA"),
    ("sha_ni", "SHA"), ("vmx", "VT-x"), ("svm", "AMD-V"),
)
_CPU_STAT_FIELDS = (
    "user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal",
)
_MEMINFO_FIELDS = {
    "MemTotal", "MemAvailable", "MemFree", "Buffers", "Cached", "SReclaimable",
    "Shmem", "SwapTotal", "SwapFree", "SwapCached", "Active", "Inactive",
    "Dirty", "Writeback", "Slab",
}

SMART_TIMEOUT_SECONDS = 12
# smartctl bits 0 and 1 mean command-line parsing or device-open failure. Bit
# 2 only reports that an ATA/SMART command failed (or a checksum warning) and
# may still accompany a useful JSON snapshot.
SMARTCTL_UNUSABLE_STATUS_MASK = 0x03
DOCKER_TIMEOUT_SECONDS = 4
MAX_DOCKER_RESPONSE_BYTES = 4 * 1024 * 1024

_SAFE_BLOCK_DEVICE_RE = re.compile(r"^/dev/[A-Za-z0-9][A-Za-z0-9._+-]{0,126}$")
_SAFE_FILESYSTEM_SOURCE_RE = re.compile(
    r"^/dev/[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)*$"
)
_SAFE_SMART_TYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9,._+-]{0,63}$")
_PSEUDO_FILESYSTEMS = {
    "aufs", "cgroup", "cgroup2", "configfs", "debugfs", "devpts", "devtmpfs",
    "efivarfs", "fusectl", "hugetlbfs", "mqueue", "nsfs", "overlay", "proc",
    "procfs", "pstore", "ramfs", "securityfs", "squashfs", "sysfs", "tmpfs",
    "tracefs",
}

_SECRET_PATTERNS = (
    re.compile(r"authorization\s*:", re.I),
    re.compile(r"\bbearer\s+\S+", re.I),
    re.compile(
        r"(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|password|passwd|secret|credential|token)\s*[:=]",
        re.I,
    ),
    re.compile(r"--(token|password)(=|\s+)", re.I),
    re.compile(r"[?&](api[_-]?key|key|token|password)=", re.I),
)


def _env_int(name, default, minimum=1):
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _truncate(value, limit, empty="-"):
    text = " ".join(str(value or "").split())
    if not text:
        text = empty
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        return REDACTED_VALUE
    return text[:limit]


def _nullable_text(value, limit):
    text = " ".join(str(value or "").split())
    if not text:
        return None
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        return REDACTED_VALUE
    return text[:limit]


def _utc_timestamp(now=None):
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    return now.astimezone(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _error(code, message, source, retryable=False, http_status=None):
    return {
        "code": code[:64],
        "message": message[:256],
        "source": source[:64],
        "retryable": bool(retryable),
        "http_status": http_status,
    }


def not_reported_hardware():
    return {
        "cpu_model": None,
        "cpu_details": None,
        "memory_details": None,
        "cpu_temperature": None,
        "disk_temperature": None,
        "disk_smart_status": "unknown",
        "disk_power_on_hours": None,
        "disk_written_bytes": None,
        "disk_read_bytes": None,
        "disk_device": None,
        "disk_smart_source": None,
        "storage": {
            "physical_disks": [],
            "filesystems": [],
            "summary": {
                "physical_disk_count": 0,
                "smart_passed": 0,
                "smart_failed": 0,
                "smart_unknown": 0,
                "temperature_min_c": None,
                "temperature_max_c": None,
                "filesystem_count": 0,
            },
            "updated_at": None,
            "stale": True,
            "error": _error("not_reported", "Storage data was not reported", "storage"),
        },
        "system_identity": None,
        "updated_at": None,
        "stale": True,
        "error": _error("not_reported", "Extension data was not reported", "hardware"),
    }


def not_reported_docker():
    return {
        "running": 0,
        "total": 0,
        "limit": 0,
        "truncated": False,
        "containers": [],
        "updated_at": None,
        "stale": True,
        "error": _error("not_reported", "Extension data was not reported", "docker"),
    }


def not_reported_hermes():
    return {
        "profiles": [],
        "updated_at": None,
        "stale": True,
        "error": _error("not_reported", "Extension data was not reported", "hermes"),
    }


def not_installed_hermes():
    """A missing optional Hermes Agent is a valid host capability state."""
    return {
        "profiles": [],
        "updated_at": _utc_timestamp(),
        "stale": False,
        "error": _error("not_installed", "Hermes Agent is not installed", "hermes", False),
    }


def read_hermes_snapshot(path, exporter_enabled=True):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        if not exporter_enabled:
            return not_installed_hermes()
        result = not_reported_hermes()
        result["error"] = _error(
            "snapshot_unavailable", "Hermes integration snapshot is unavailable", "hermes-snapshot", True
        )
        return result
    except (OSError, TypeError, ValueError):
        payload = None
    if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
        result = not_reported_hermes()
        result["error"] = _error(
            "snapshot_unavailable",
            "Hermes integration snapshot is unavailable",
            "hermes-snapshot",
            True,
        )
        return result
    profiles = payload.get("profiles")[:MAX_HERMES_PROFILES]
    if not all(isinstance(item, dict) for item in profiles):
        result = not_reported_hermes()
        result["error"] = _error(
            "snapshot_invalid",
            "Hermes integration snapshot is invalid",
            "hermes-snapshot",
            True,
        )
        return result
    return {
        "profiles": profiles,
        "updated_at": payload.get("updated_at"),
        "stale": bool(payload.get("stale", True)),
        "error": payload.get("error") if isinstance(payload.get("error"), dict) else None,
    }


def read_os_release(path):
    values = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                values[key.strip()] = value.replace(r"\"", '"')
    except (OSError, UnicodeError):
        return {}
    return values


def collect_host_os(path):
    values = read_os_release(path)
    if not values:
        return "unknown", _error(
            "host_os_unavailable",
            "Host operating system data is unavailable",
            "host-os",
            True,
        )
    pretty = values.get("PRETTY_NAME")
    if pretty:
        return _truncate(pretty, 128, "unknown"), None
    name = values.get("NAME") or values.get("ID")
    version = values.get("VERSION_ID") or values.get("VERSION")
    display = " ".join(part for part in (name, version) if part)
    if display:
        return _truncate(display, 128, "unknown"), None
    return "unknown", _error(
        "host_os_unavailable",
        "Host operating system data is unavailable",
        "host-os",
        False,
    )


def _read_key_value_file(path, allowed_keys):
    values = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key not in allowed_keys:
                    continue
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                values[key] = value.replace(r"\"", '"')
    except (OSError, UnicodeError):
        return {}
    return values


def collect_system_identity(os_release_path, dsm_version_path=None, uname_result=None):
    """Collect only bounded OS identity strings; never derive device identity here."""
    dsm_values = _read_key_value_file(
        dsm_version_path or "/host/etc.defaults/VERSION",
        {"productversion", "buildnumber", "smallfixnumber", "buildphase"},
    )
    if dsm_values.get("productversion"):
        release = dsm_values["productversion"]
        build = dsm_values.get("buildnumber")
        if build:
            release = "%s-%s" % (release, build)
        update = dsm_values.get("smallfixnumber")
        if update and update not in ("0", "00"):
            release = "%s Update %s" % (release, update)
        distribution = "Synology DSM"
        pretty_name = "%s %s" % (distribution, release)
        source = "dsm-version"
    else:
        values = read_os_release(os_release_path)
        distribution = values.get("NAME") or values.get("ID") or "unknown"
        release = values.get("VERSION_ID") or values.get("VERSION") or None
        pretty_name = values.get("PRETTY_NAME") or " ".join(
            part for part in (distribution, release) if part
        ) or "unknown"
        source = "os-release" if values else "unavailable"
    try:
        uname = uname_result or os.uname()
        kernel_release = uname.release
        architecture = uname.machine
    except (AttributeError, OSError):
        kernel_release = None
        architecture = None
    return {
        "distribution": _nullable_text(distribution, MAX_SYSTEM_IDENTITY_TEXT_LENGTH),
        "release_version": _nullable_text(release, MAX_SYSTEM_IDENTITY_TEXT_LENGTH),
        "pretty_name": _nullable_text(pretty_name, MAX_SYSTEM_IDENTITY_TEXT_LENGTH),
        "kernel_release": _nullable_text(kernel_release, MAX_SYSTEM_IDENTITY_TEXT_LENGTH),
        "architecture": _nullable_text(architecture, MAX_SYSTEM_IDENTITY_TEXT_LENGTH),
        "source": source,
    }


def collect_client_build(environ=None, protocol=None):
    """Return a complete Device v2 image build record without runtime git.

    Provenance is optional.  An incomplete development image must therefore
    omit the whole object instead of causing an otherwise valid device report
    to be rejected by the strict server-side contract.
    """
    environment = os.environ if environ is None else environ
    values = {
        "version": _nullable_text(environment.get("HERMESSTATUS_CLIENT_VERSION"), 64),
        "revision": _nullable_text(environment.get("HERMESSTATUS_CLIENT_REVISION"), 64),
        "build_time": _nullable_text(environment.get("HERMESSTATUS_CLIENT_BUILD_TIME"), 64),
        "protocol": _nullable_text(protocol or environment.get("HERMESSTATUS_CLIENT_PROTOCOL"), 64),
    }
    if not all(values[key] is not None for key in ("version", "revision", "protocol")):
        return None
    if values["protocol"] != "device_v2" or not re.fullmatch(r"[0-9a-f]{40}", values["revision"]):
        return None
    if values["build_time"] is not None and not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", values["build_time"]
    ):
        return None
    return values


def parse_smart_devices_value(value):
    """Parse the optional SMART_DEVICES JSON environment value safely."""
    if value in (None, ""):
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list) or len(parsed) > MAX_PHYSICAL_DISKS:
        return []
    normalized = []
    for entry in parsed:
        candidate = _parse_smart_device(entry)
        if candidate is None or candidate in normalized:
            if candidate is None:
                return []
            continue
        normalized.append(candidate)
    return normalized


def _default_command_runner(command, timeout):
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=timeout,
        env=dict(os.environ, LC_ALL="C"),
    )
    return completed.returncode, completed.stdout or ""


def _cpu_model_from_lscpu_json(output):
    try:
        data = json.loads(output)
    except (TypeError, ValueError):
        return None
    for item in data.get("lscpu", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip().rstrip(":").lower()
        if field == "model name":
            return _nullable_text(item.get("data"), MAX_CPU_MODEL_LENGTH)
    return None


def _lscpu_values(output):
    try:
        data = json.loads(output)
    except (TypeError, ValueError):
        return {}
    values = {}
    for item in data.get("lscpu", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip().rstrip(":").lower()
        value = item.get("data")
        if field and value not in (None, "") and field not in values:
            values[field] = value
    return values


def _lscpu_integer(value):
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if 0 < result <= 65536 else None


def _lscpu_float(value):
    try:
        result = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return round(result, 1) if 0 <= result <= 1000000 else None


def _cpuinfo_current_mhz(path):
    """Return a bounded average of per-CPU ``cpu MHz`` observations."""
    values = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= MAX_CPUINFO_LINES:
                    break
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                if key.strip().lower() != "cpu mhz":
                    continue
                mhz = _lscpu_float(value)
                if mhz is not None:
                    values.append(mhz)
    except OSError:
        return None
    return _lscpu_float(sum(values) / len(values)) if values else None


def collect_cpu_details(command_runner=None, cpuinfo_path="/proc/cpuinfo"):
    """Collect a bounded allowlist of CPU topology facts from ``lscpu``."""
    runner = command_runner or _default_command_runner
    try:
        returncode, output = runner(["lscpu", "--json"], 3)
        values = _lscpu_values(output) if returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        values = {}
    if not values:
        return None, _error(
            "cpu_details_unavailable", "Host CPU details are unavailable", "lscpu", True
        )
    details = {
        target: _nullable_text(values.get(source), MAX_CPU_VENDOR_LENGTH if target == "vendor" else MAX_CPU_TEXT_LENGTH)
        for source, target in _CPU_LSCPU_TEXT_FIELDS.items()
    }
    details.update({
        target: _lscpu_integer(values.get(source))
        for source, target in _CPU_LSCPU_INTEGER_FIELDS.items()
    })
    details.update({
        target: _lscpu_float(values.get(source))
        for source, target in _CPU_LSCPU_FLOAT_FIELDS.items()
    })
    if details["current_mhz"] is None:
        details["current_mhz"] = _cpuinfo_current_mhz(cpuinfo_path)
    details["model_name"] = _nullable_text(values.get("model name"), MAX_CPU_MODEL_LENGTH)
    # Keep only named, user-meaningful CPU capabilities.  The full lscpu
    # flags value is intentionally never projected as arbitrary command output.
    flags = set(str(values.get("flags") or values.get("features") or "").lower().split())
    instruction_sets = [label for flag, label in _CPU_INSTRUCTION_SET_FLAGS if flag in flags]
    details["instruction_sets"] = ", ".join(instruction_sets) or None
    return details, None


def collect_cpu_model(command_runner=None, cpuinfo_path="/proc/cpuinfo"):
    runner = command_runner or _default_command_runner
    model = None
    try:
        returncode, output = runner(["lscpu", "--json"], 3)
        if returncode == 0:
            model = _cpu_model_from_lscpu_json(output)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    if not model:
        try:
            with open(cpuinfo_path, "r", encoding="utf-8", errors="replace") as handle:
                fallback = None
                for line in handle:
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    if key == "model name":
                        model = _nullable_text(value, MAX_CPU_MODEL_LENGTH)
                        break
                    if key in ("hardware", "processor") and not str(value).strip().isdigit():
                        fallback = fallback or _nullable_text(value, MAX_CPU_MODEL_LENGTH)
                model = model or fallback
        except OSError:
            pass
    if model:
        return model, None
    return None, _error(
        "cpu_model_unavailable",
        "Host CPU model is unavailable",
        "cpu-model",
        False,
    )


def _read_cpu_stat(path="/proc/stat"):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.startswith("cpu "):
                    continue
                values = line.split()[1:]
                counters = []
                for index in range(len(_CPU_STAT_FIELDS)):
                    try:
                        value = int(values[index]) if index < len(values) else 0
                    except (TypeError, ValueError):
                        return None
                    if value < 0:
                        return None
                    counters.append(value)
                return counters
    except OSError:
        pass
    return None


def collect_cpu_usage(cpu_stat_path="/proc/stat", sleep_func=None):
    """Sample aggregate CPU time twice so iowait is an actual interval share."""
    pause = sleep_func or time.sleep
    before = _read_cpu_stat(cpu_stat_path)
    if before is None:
        return None, _error("cpu_usage_unavailable", "CPU usage is unavailable", "proc-stat", True)
    try:
        pause(CPU_USAGE_SAMPLE_SECONDS)
    except (TypeError, ValueError):
        return None, _error("cpu_usage_unavailable", "CPU usage is unavailable", "proc-stat", True)
    after = _read_cpu_stat(cpu_stat_path)
    if after is None:
        return None, _error("cpu_usage_unavailable", "CPU usage is unavailable", "proc-stat", True)
    delta = [max(0, right - left) for left, right in zip(before, after)]
    total = sum(delta)
    if total <= 0:
        return None, _error("cpu_usage_unavailable", "CPU usage is unavailable", "proc-stat", True)
    usage = {
        "%s_percent" % field: round((delta[index] * 100.0) / total, 1)
        for index, field in enumerate(_CPU_STAT_FIELDS)
    }
    usage["total_percent"] = round(max(0.0, 100.0 - usage["idle_percent"]), 1)
    return usage, None


def collect_memory_details(meminfo_path="/proc/meminfo"):
    values = {}
    try:
        with open(meminfo_path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = re.match(r"^([A-Za-z]+):\s*(\d+)\s*kB$", line.strip())
                if not match or match.group(1) not in _MEMINFO_FIELDS:
                    continue
                values[match.group(1)] = int(match.group(2)) * 1024
    except (OSError, ValueError):
        values = {}
    total = values.get("MemTotal")
    if total is None or not _valid_counter(total) or total <= 0:
        return None, _error("memory_unavailable", "Host memory details are unavailable", "meminfo", True)
    available = values.get("MemAvailable")
    if available is None:
        available = sum(values.get(name, 0) for name in ("MemFree", "Buffers", "Cached", "SReclaimable"))
    available = min(total, max(0, available))
    cached = max(0, values.get("Cached", 0) + values.get("SReclaimable", 0) - values.get("Shmem", 0))
    swap_total = values.get("SwapTotal", 0)
    swap_free = min(swap_total, max(0, values.get("SwapFree", 0)))
    return {
        "total_bytes": total,
        "used_bytes": max(0, total - available),
        "available_bytes": available,
        "free_bytes": values.get("MemFree"),
        "buffers_bytes": values.get("Buffers"),
        "cached_bytes": cached,
        "reclaimable_bytes": values.get("SReclaimable"),
        "active_bytes": values.get("Active"),
        "inactive_bytes": values.get("Inactive"),
        "dirty_bytes": values.get("Dirty"),
        "writeback_bytes": values.get("Writeback"),
        "slab_bytes": values.get("Slab"),
        "swap_total_bytes": swap_total,
        "swap_used_bytes": max(0, swap_total - swap_free),
        "swap_free_bytes": swap_free,
        "swap_cached_bytes": values.get("SwapCached"),
    }, None


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def collect_hwmon_temperatures(root="/sys/class/hwmon"):
    sensors = []
    for base in sorted(glob.glob(os.path.join(root, "hwmon*"))):
        chip = _read_text(os.path.join(base, "name")) or os.path.basename(base)
        for input_path in sorted(glob.glob(os.path.join(base, "temp*_input"))):
            match = re.search(r"temp(\d+)_input$", input_path)
            index = match.group(1) if match else ""
            label = _read_text(os.path.join(base, "temp%s_label" % index))
            raw_value = _read_text(input_path)
            try:
                value = int(raw_value) / 1000.0
            except (TypeError, ValueError):
                continue
            if value < -100 or value > 250:
                continue
            source = " ".join(part for part in (chip, label) if part).strip() or chip
            sensors.append(
                {
                    "value": round(value, 1),
                    "label": _nullable_text(label or chip, MAX_TEMPERATURE_SOURCE_LENGTH),
                    "source": _truncate(source, MAX_TEMPERATURE_SOURCE_LENGTH, "hwmon"),
                }
            )
    return sensors


def pick_cpu_temperature(sensors):
    keywords = ("coretemp", "cpu", "package", "k10temp")
    cpu_sensors = [
        sensor for sensor in sensors
        if any(
            keyword in str(sensor.get(field) or "").lower()
            for field in ("source", "label")
            for keyword in keywords
        )
    ]
    selected = cpu_sensors or list(sensors or [])
    if not selected:
        return None
    return max(selected, key=lambda sensor: float(sensor.get("value") or -101))


def _parse_smart_device(value):
    if isinstance(value, dict):
        device = value.get("path")
        device_type = value.get("type") or ""
    elif isinstance(value, (tuple, list)) and len(value) == 2:
        device, device_type = value
    else:
        try:
            parts = shlex.split(str(value))
        except (TypeError, ValueError):
            return None
        if not parts:
            return None
        device = next((part for part in parts if part.startswith("/dev/")), "")
        device_type = ""
        if "-d" in parts:
            index = parts.index("-d")
            if index + 1 < len(parts):
                device_type = parts[index + 1]
    if not isinstance(device, str) or not _SAFE_BLOCK_DEVICE_RE.fullmatch(device):
        return None
    if not isinstance(device_type, str) or (
        device_type and not _SAFE_SMART_TYPE_RE.fullmatch(device_type)
    ):
        return None
    return device, device_type


def _base_block_device(device):
    if re.match(r"^/dev/(?:sd|vd|hd|xvd)[a-z]+\d+$", device):
        return re.sub(r"\d+$", "", device)
    return re.sub(r"p\d+$", "", device)


def smart_candidates(configured="auto", command_runner=None):
    runner = command_runner or _default_command_runner
    if configured not in (None, "", "auto"):
        entries = configured if isinstance(configured, (list, tuple)) else [configured]
        devices = []
        for entry in entries:
            candidate = _parse_smart_device(entry)
            if candidate and candidate not in devices:
                devices.append(candidate)
        return devices[:MAX_PHYSICAL_DISKS]

    devices = []
    try:
        _, output = runner(["smartctl", "--scan"], 4)
        for line in output.splitlines():
            candidate = _parse_smart_device(line.split("#", 1)[0].strip())
            if candidate and candidate not in devices:
                devices.append(candidate)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                device = line.split(None, 1)[0] if line.strip() else ""
                if not device.startswith("/dev/"):
                    continue
                device = _base_block_device(device)
                candidate = (device, "")
                if candidate not in devices:
                    devices.append(candidate)
    except OSError:
        pass
    for pattern in ("/dev/nvme*n1", "/dev/sd?", "/dev/vd?"):
        for device in sorted(glob.glob(pattern)):
            candidate = (device, "")
            if candidate not in devices:
                devices.append(candidate)
    return devices[:MAX_PHYSICAL_DISKS]


def _coerce_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, dict):
        for key in ("value", "raw", "current"):
            if key in value:
                found = _coerce_int(value[key])
                if found is not None:
                    return found
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _hex_or_int(value):
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def _device_stat_json_value(data, page_number, offset, description):
    statistics = data.get("ata_device_statistics") if isinstance(data, dict) else None
    pages = statistics.get("pages", []) if isinstance(statistics, dict) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_value = _hex_or_int(page.get("number", page.get("page")))
        if page_value != page_number:
            continue
        for item in page.get("table", page.get("entries", [])) or []:
            if not isinstance(item, dict):
                continue
            item_offset = _hex_or_int(item.get("offset"))
            item_name = str(item.get("name") or item.get("description") or "").strip().lower()
            if item_offset == offset or item_name == description.lower():
                result = _coerce_int(item.get("value", item.get("raw")))
                if result is not None:
                    return result
    return None


def _device_stat_text_value(text, page, offset, description):
    pattern = re.compile(
        r"^\s*%s\s+%s\s+\d+\s+(-?\d+)\s+---\s+%s\s*$"
        % (re.escape(page), re.escape(offset), re.escape(description)),
        re.I | re.M,
    )
    match = pattern.search(text or "")
    return int(match.group(1)) if match else None


def _smart_health(data, text):
    match = re.search(
        r"SMART overall-health self-assessment test result:\s*([A-Z]+)",
        text or "",
        re.I,
    )
    if match:
        result = match.group(1).lower()
        return "passed" if result == "passed" else "failed"
    status = data.get("smart_status") if isinstance(data, dict) else None
    if isinstance(status, dict) and isinstance(status.get("passed"), bool):
        return "passed" if status["passed"] else "failed"
    return "unknown"


def _smartctl_query_failed(data):
    """Return true when smartctl could not open or query the device.

    smartctl emits a syntactically valid JSON document even when opening the
    target device is denied.  That document must not be treated as a SMART
    snapshot: doing so turns a permission failure into an unexplained
    ``unknown`` health value.
    """
    metadata = data.get("smartctl") if isinstance(data, dict) else None
    if not isinstance(metadata, dict):
        return False
    exit_status = _coerce_int(metadata.get("exit_status"))
    if exit_status is None:
        return False
    # Reject only command-line and device-open failures. A failing individual
    # SMART command or checksum warning (bit 2) may still leave enough JSON to
    # report health and temperature, so keep that snapshot.
    return bool(exit_status & SMARTCTL_UNUSABLE_STATUS_MASK)


def _smart_overall_status_incomplete(data, text):
    """Return true when a bridge cannot provide a trustworthy SMART verdict."""
    fragments = [text or ""]
    metadata = data.get("smartctl") if isinstance(data, dict) else None
    if isinstance(metadata, dict):
        for message in metadata.get("messages") or []:
            if isinstance(message, dict):
                fragments.append(str(message.get("string") or ""))
    combined = "\n".join(fragments).lower()
    return "smart status not supported" in combined or "incomplete response" in combined


def _smart_attribute_fallback_available(data, text):
    """Return true only for a readable SMART attribute/threshold table.

    USB bridges may prevent ATA SMART RETURN STATUS while still allowing the
    attributes which smartctl uses for its explicit overall-health fallback.
    A bare ``PASSED`` string is not sufficient evidence: require either the
    structured table or its bounded text representation as well.
    """
    attributes = data.get("ata_smart_attributes") if isinstance(data, dict) else None
    table = attributes.get("table") if isinstance(attributes, dict) else None
    if isinstance(table, list) and any(isinstance(item, dict) for item in table):
        return True
    normalized = text or ""
    return bool(
        re.search(r"^\s*ID#\s+ATTRIBUTE_NAME\b", normalized, re.I | re.M)
        and re.search(r"^\s*\d+\s+\S+\s+\S+", normalized, re.M)
    )


def _json_nested_value(data, keys):
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in keys:
                result = _coerce_int(value)
                if result is not None:
                    return result
            result = _json_nested_value(value, keys)
            if result is not None:
                return result
    elif isinstance(data, list):
        for value in data:
            result = _json_nested_value(value, keys)
            if result is not None:
                return result
    return None


def _logical_sector_size(data, text):
    size = _json_nested_value(data, {"logical_block_size", "logical_sector_size"})
    if size is None:
        patterns = (
            r"Sector Size:\s*(\d+)\s+bytes logical",
            r"Logical (?:block|sector) size:\s*(\d+)\s+bytes",
        )
        for pattern in patterns:
            match = re.search(pattern, text or "", re.I)
            if match:
                size = int(match.group(1))
                break
    if size is None or size < 128 or size > 1048576:
        return None
    return size


def _smart_values(data, text):
    def stat(page_number, page_text, offset, description):
        value = _device_stat_json_value(data, page_number, int(offset, 16), description)
        if value is None:
            value = _device_stat_text_value(text, page_text, offset, description)
        return value

    current = stat(5, "0x05", "0x008", "Current Temperature")
    highest = stat(5, "0x05", "0x020", "Highest Temperature")
    lowest = stat(5, "0x05", "0x028", "Lowest Temperature")
    hours = stat(1, "0x01", "0x010", "Power-on Hours")
    written_sectors = stat(1, "0x01", "0x018", "Logical Sectors Written")
    read_sectors = stat(1, "0x01", "0x028", "Logical Sectors Read")

    temperature_source = "smartctl-device-statistics"
    if current is None:
        current = _json_nested_value(data.get("temperature", {}) if isinstance(data, dict) else {}, {"current"})
        temperature_source = "smartctl-json"
    sector_size = _logical_sector_size(data, text)
    return {
        "health": _smart_health(data, text),
        "current": current,
        "highest": highest,
        "lowest": lowest,
        "hours": hours,
        "written_sectors": written_sectors,
        "read_sectors": read_sectors,
        "sector_size": sector_size,
        "temperature_source": temperature_source,
    }


def _valid_temperature(value):
    return value is None or (-100 <= value <= 250)


def _valid_counter(value):
    return value is None or (0 <= value <= MAX_SAFE_INTEGER)


def _smart_model(data):
    if not isinstance(data, dict):
        return None
    model = data.get("model_name") or data.get("model_family")
    device = data.get("device")
    if not model and isinstance(device, dict):
        model = device.get("model_name")
    return _nullable_text(model, MAX_DISK_MODEL_LENGTH)


def _smart_capacity_bytes(data):
    if not isinstance(data, dict):
        return None
    user_capacity = data.get("user_capacity")
    value = user_capacity.get("bytes") if isinstance(user_capacity, dict) else None
    value = _coerce_int(value)
    return value if _valid_counter(value) else None


def _collect_smart_candidate(candidate, device_type, command_runner=None):
    """Collect one SMART target; a failure never affects a sibling target."""
    runner = command_runner or _default_command_runner
    typed = ["-d", device_type] if device_type else []
    data = {}
    text = ""
    json_ok = False
    try:
        returncode, output = runner(
            ["smartctl", "-x", "-j"] + typed + [candidate], SMART_TIMEOUT_SECONDS
        )
        parsed = json.loads(output) if output else None
        if (
            isinstance(parsed, dict)
            and not _smartctl_query_failed(parsed)
            and not (int(returncode) & SMARTCTL_UNUSABLE_STATUS_MASK)
        ):
            data = parsed
            json_ok = True
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        pass

    # Text remains authoritative for the ATA Device Statistics table; JSON
    # provides structured fallback values and the logical sector size.
    try:
        _, output = runner(["smartctl", "-x"] + typed + [candidate], SMART_TIMEOUT_SECONDS)
        if "START OF READ SMART DATA SECTION" in output or "SMART overall-health" in output:
            text = output
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    if not data and not text:
        return None, _error(
            "smartctl_unavailable", "SMART data is unavailable", "smartctl", True
        )
    values = _smart_values(data, text)
    incomplete_health = _smart_overall_status_incomplete(data, text)
    # Some USB/SATA bridges cannot return ATA SMART RETURN STATUS yet expose
    # the complete attribute/threshold table.  smartctl explicitly reports
    # its attribute-check fallback in that case; keep that bounded verdict,
    # while projecting its lower quality separately from native SMART status.
    trusted_health = values["health"] in {"passed", "failed"}
    attribute_fallback = (
        incomplete_health
        and trusted_health
        and _smart_attribute_fallback_available(data, text)
    )
    if attribute_fallback:
        health_source = "attribute_check"
        native_status = "unavailable"
        completeness = "partial"
    elif incomplete_health:
        # A bridge that cannot perform RETURN STATUS needs independent
        # attribute/threshold evidence before its health result is trusted.
        values["health"] = "unknown"
        health_source = "unknown"
        native_status = "unavailable"
        completeness = "unavailable"
    elif trusted_health:
        health_source = "native_status"
        native_status = "available"
        completeness = "complete"
    else:
        # Do not manufacture a quality level when neither native status nor
        # the attribute-check fallback yielded a bounded health result.
        health_source = "unknown"
        native_status = "unavailable" if incomplete_health else "unknown"
        completeness = "unavailable"
    # A transport mismatch can produce syntactically valid smartctl output
    # containing inventory fields but no trustworthy overall-health result.
    # Retain any bounded observations for the per-disk row, but never label
    # that partial snapshot healthy or let it hide an unavailable SMART state.
    invalid_value = values["health"] not in {"passed", "failed"} or not all(
        _valid_temperature(values[key]) for key in ("current", "highest", "lowest")
    ) or not all(
        _valid_counter(values[key])
        for key in ("hours", "written_sectors", "read_sectors")
    )
    if invalid_value:
        for key in ("current", "highest", "lowest"):
            if not _valid_temperature(values[key]):
                values[key] = None
        for key in ("hours", "written_sectors", "read_sectors"):
            if not _valid_counter(values[key]):
                values[key] = None
    written_bytes = None
    read_bytes = None
    sector_error = False
    if values["written_sectors"] is not None or values["read_sectors"] is not None:
        if values["sector_size"] is None:
            sector_error = True
        else:
            if values["written_sectors"] is not None:
                written_bytes = values["written_sectors"] * values["sector_size"]
            if values["read_sectors"] is not None:
                read_bytes = values["read_sectors"] * values["sector_size"]
            if not _valid_counter(written_bytes):
                written_bytes = None
                invalid_value = True
            if not _valid_counter(read_bytes):
                read_bytes = None
                invalid_value = True
    result = {
        "device": _nullable_text(candidate, MAX_DISK_DEVICE_LENGTH),
        "source": "smartctl-json" if json_ok and not text else ("smartctl-json-text" if json_ok else "smartctl-text"),
        "health": values["health"],
        "current": values["current"],
        "highest": values["highest"],
        "lowest": values["lowest"],
        "hours": values["hours"],
        "written_bytes": written_bytes,
        "read_bytes": read_bytes,
        "temperature_source": values["temperature_source"],
        "model": _smart_model(data),
        "capacity_bytes": _smart_capacity_bytes(data),
        "completeness": completeness,
        "health_source": health_source,
        "native_status": native_status,
    }
    if sector_error:
        return result, _error(
            "sector_size_unknown", "Logical sector size is unavailable", "smartctl", False
        )
    if attribute_fallback:
        return result, _error(
            "smart_return_status_unavailable",
            "SMART native return status is unavailable; attribute health fallback was used",
            "smartctl",
            False,
        )
    if invalid_value:
        return result, _error(
            "smart_value_invalid", "One or more SMART values are invalid", "smartctl", False
        )
    return result, None


def collect_smart_devices(devices="auto", command_runner=None):
    """Return one bounded result per configured/discovered physical device."""
    candidates = smart_candidates(devices, command_runner)
    records = []
    errors = []
    for candidate, device_type in candidates:
        smart, error = _collect_smart_candidate(candidate, device_type, command_runner)
        records.append((candidate, smart, error))
        if error:
            errors.append(error)
    # An explicit empty Device v2 allowlist is a valid operator choice: it
    # requests topology-only disk inventory without attempting SMART.  It is
    # distinct from automatic discovery finding no usable target.
    explicitly_disabled = isinstance(devices, (list, tuple)) and not devices
    if not candidates and not explicitly_disabled:
        errors.append(_error("smartctl_unavailable", "SMART data is unavailable", "smartctl", True))
    # An attribute/threshold health fallback is a usable SMART observation
    # with explicitly lower completeness.  Keep its per-disk warning so the
    # Hardware page can explain the source, but do not turn the entire storage
    # or hardware domain into a failure solely because native RETURN STATUS is
    # unavailable through a USB bridge.
    domain_errors = [
        error for error in errors
        if error.get("code") != "smart_return_status_unavailable"
    ]
    return records, _select_error(domain_errors)


def collect_smart(device="auto", command_runner=None):
    """Compatibility helper for existing single-target callers.

    New hardware payloads use ``collect_smart_devices`` so multiple disks never
    silently choose the first successful device for legacy singular fields.
    """
    records, error = collect_smart_devices(device, command_runner)
    for _, smart, smart_error in records:
        if smart is not None:
            return smart, smart_error
    return None, error


def _block_name(value):
    if not isinstance(value, str):
        return None
    name = value.rsplit("/", 1)[-1]
    return name if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,126}", name) else None


def _append_block_node(graph, value, parent_name=None):
    if not isinstance(value, dict) or len(graph["nodes"]) >= MAX_BLOCK_GRAPH_NODES:
        return
    name = _block_name(value.get("kname") or value.get("name"))
    if not name:
        return
    node = graph["nodes"].setdefault(name, {"name": name})
    node["type"] = _nullable_text(value.get("type"), 32)
    node["size"] = _coerce_int(value.get("size"))
    node["model"] = _nullable_text(value.get("model"), MAX_DISK_MODEL_LENGTH)
    node["transport"] = _nullable_text(value.get("tran"), 32)
    pkname = _block_name(value.get("pkname"))
    if pkname:
        node["parent"] = pkname
    elif parent_name and parent_name != name:
        node.setdefault("parent", parent_name)
    for alias in (value.get("name"), value.get("kname"), value.get("path"), "/dev/" + name):
        if isinstance(alias, str) and alias:
            graph["aliases"][alias] = name
    for child in value.get("children") or []:
        _append_block_node(graph, child, name)


def build_block_device_graph(lsblk_payload, sys_block_root="/sys/class/block"):
    """Create a bounded logical-device → physical-disk graph.

    ``lsblk`` supplies names, types and display metadata.  The kernel's
    ``slaves`` directory supplies the authoritative relationship for MD, LVM
    and device-mapper when it is safely visible to the client.
    """
    graph = {"nodes": {}, "aliases": {}}
    devices = lsblk_payload.get("blockdevices", []) if isinstance(lsblk_payload, dict) else []
    for device in devices:
        _append_block_node(graph, device)
    for name, node in list(graph["nodes"].items()):
        if len(graph["nodes"]) > MAX_BLOCK_GRAPH_NODES:
            break
        slaves = []
        for slave in node.get("slaves", []) if isinstance(node.get("slaves"), list) else []:
            normalized = _block_name(slave)
            if normalized:
                slaves.append(normalized)
        if not slaves:
            try:
                entries = os.listdir(os.path.join(sys_block_root, name, "slaves"))
            except OSError:
                entries = []
            for slave in entries[:MAX_BLOCK_GRAPH_NODES]:
                normalized = _block_name(slave)
                if normalized:
                    slaves.append(normalized)
        if slaves:
            node["slaves"] = sorted(set(slaves))[:MAX_BLOCK_GRAPH_NODES]
    return graph


def collect_block_device_graph(command_runner=None, sys_block_root="/sys/class/block"):
    runner = command_runner or _default_command_runner
    command = [
        "lsblk", "--json", "--bytes", "--output",
        "NAME,KNAME,PKNAME,PATH,TYPE,SIZE,MODEL,TRAN",
    ]
    try:
        returncode, output = runner(command, 4)
        parsed = json.loads(output) if returncode == 0 and output else None
        if isinstance(parsed, dict) and isinstance(parsed.get("blockdevices"), list):
            return build_block_device_graph(parsed, sys_block_root), None
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        pass
    return {"nodes": {}, "aliases": {}}, _error(
        "block_graph_unavailable", "Block-device topology is unavailable", "lsblk", True
    )


def resolve_backing_physical_disks(block_device, graph):
    """Resolve a filesystem source through MD/LVM/device-mapper safely."""
    aliases = graph.get("aliases", {}) if isinstance(graph, dict) else {}
    nodes = graph.get("nodes", {}) if isinstance(graph, dict) else {}
    start = aliases.get(block_device) or aliases.get(str(block_device or ""))
    start = start or _block_name(block_device)
    if start not in nodes:
        return []
    pending = [(start, 0)]
    visited = set()
    physical = set()
    while pending and len(visited) < MAX_BLOCK_GRAPH_NODES:
        name, depth = pending.pop()
        if name in visited or depth > MAX_BLOCK_GRAPH_DEPTH:
            continue
        visited.add(name)
        node = nodes.get(name)
        if not isinstance(node, dict):
            continue
        if node.get("type") == "disk":
            physical.add(name)
            continue
        next_nodes = node.get("slaves") or ([node["parent"]] if node.get("parent") else [])
        for child in next_nodes:
            normalized = _block_name(child)
            if normalized and normalized in nodes:
                pending.append((normalized, depth + 1))
    return sorted(physical)


def _stack_type(source, graph, fs_type=None):
    if isinstance(fs_type, str) and fs_type.lower() == "btrfs":
        return "btrfs"
    nodes = graph.get("nodes", {}) if isinstance(graph, dict) else {}
    aliases = graph.get("aliases", {}) if isinstance(graph, dict) else {}
    name = aliases.get(source) or _block_name(source)
    node = nodes.get(name) if name else None
    if not isinstance(node, dict):
        return "unknown"
    node_type = node.get("type")
    if node_type == "lvm":
        return "lvm"
    if node_type in {"crypt", "dm"} or str(name).startswith("dm-"):
        return "device_mapper"
    if isinstance(node_type, str) and node_type.startswith("raid"):
        return "mdraid"
    return "plain" if node_type in {"disk", "part"} else "unknown"


def _findmnt_for_probe(probe_path, command_runner):
    try:
        returncode, output = command_runner(
            ["findmnt", "--json", "--target", probe_path], 4
        )
        parsed = json.loads(output) if returncode == 0 and output else None
        entries = parsed.get("filesystems", []) if isinstance(parsed, dict) else []
        entry = entries[0] if isinstance(entries, list) and entries else None
        return entry if isinstance(entry, dict) else None
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        return None


def _normalized_filesystem_source(value):
    """Return the safe block-device component of a findmnt source, if any.

    `findmnt` represents a bind mount or Btrfs subvolume as
    `/dev/sda1[/path]`.  The bracket suffix is local mount metadata, not a
    block-device identity, so retain only the bounded device component.  Other
    source forms (for example an NFS export) are intentionally not forwarded:
    a filesystem can still be healthy without revealing a remote endpoint.
    """
    source = _nullable_text(value, MAX_FILESYSTEM_SOURCE_LENGTH)
    if not source:
        return None
    match = re.fullmatch(
        r"(/dev/[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)*)(?:\[[^\]\x00-\x1f]{0,384}\])?",
        source,
    )
    if not match:
        return None
    device = match.group(1)
    # This deliberately permits safe mapper paths such as
    # /dev/mapper/vg-root, while refusing traversal and non-device sources.
    return (
        device
        if _SAFE_FILESYSTEM_SOURCE_RE.fullmatch(device) and ".." not in device
        else None
    )


def _configured_mountpoint(value):
    """Preserve an already-validated display mountpoint byte-for-byte.

    The contract parser accepts legal whitespace in a path.  Do not route this
    field through generic display-text normalization: doing so would turn a
    configured path into a different label.  The collector remains defensive
    for direct callers and enforces the same 512-character wire limit.
    """
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_MOUNTPOINT_LENGTH
        or "\x00" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return None
    path = PurePosixPath(value)
    if not path.is_absolute() or str(path) != value or ".." in path.parts:
        return None
    return value


def collect_filesystems(filesystem_probes, block_graph, command_runner=None, statvfs_func=None):
    """Collect only explicitly configured, read-only filesystem probe mounts."""
    runner = command_runner or _default_command_runner
    statvfs = statvfs_func or os.statvfs
    filesystems = []
    errors = []
    for probe in list(filesystem_probes or [])[:MAX_FILESYSTEMS]:
        if not isinstance(probe, dict):
            continue
        mountpoint = _configured_mountpoint(probe.get("mountpoint"))
        probe_path = probe.get("probe_path")
        if not mountpoint or not isinstance(probe_path, str):
            continue
        entry = _findmnt_for_probe(probe_path, runner)
        source = _normalized_filesystem_source(entry.get("source")) if entry else None
        fs_type = _nullable_text(entry.get("fstype"), MAX_FILESYSTEM_TYPE_LENGTH) if entry else None
        item = {
            "source": source,
            "mountpoint": mountpoint,
            "fs_type": fs_type,
            "total_bytes": None,
            "used_bytes": None,
            "available_bytes": None,
            "usage_percent": None,
            # `findmnt` reports one source for Btrfs, but that source does not
            # authoritatively enumerate every member of a multi-device Btrfs
            # filesystem.  An empty relation is safer than presenting an
            # incomplete single-disk relationship as complete.
            "backing_disk_ids": (
                [] if isinstance(fs_type, str) and fs_type.lower() == "btrfs" else
                resolve_backing_physical_disks(source, block_graph)[:MAX_FILESYSTEM_BACKING_DISKS]
                if source
                else []
            ),
            "stack_type": _stack_type(source, block_graph, fs_type) if source else "unknown",
            "collection_status": "healthy",
            "error": None,
        }
        if not entry or (fs_type and fs_type.lower() in _PSEUDO_FILESYSTEMS):
            item["collection_status"] = "unavailable"
            item["error"] = _error(
                "filesystem_unavailable", "Filesystem metadata is unavailable", "findmnt", True
            )
            errors.append(item["error"])
            filesystems.append(item)
            continue
        try:
            stats = statvfs(probe_path)
            block_size = int(stats.f_frsize or stats.f_bsize)
            total = int(stats.f_blocks) * block_size
            available = int(stats.f_bavail) * block_size
            # f_bfree is the filesystem-wide free block count. f_bavail is
            # user-available capacity and deliberately excludes reserved
            # blocks, so use f_bfree for used capacity while still reporting
            # f_bavail as available capacity.
            used = max(0, int(stats.f_blocks - stats.f_bfree) * block_size)
            if not all(_valid_counter(value) for value in (total, available, used)) or total <= 0:
                raise ValueError("invalid statvfs values")
            item.update({
                "total_bytes": total,
                "used_bytes": used,
                "available_bytes": available,
                "usage_percent": round((used * 100.0) / total, 1),
            })
        except (OSError, TypeError, ValueError, OverflowError):
            item["collection_status"] = "unavailable"
            item["error"] = _error(
                "filesystem_probe_unavailable", "Filesystem usage is unavailable", "statvfs", True
            )
            errors.append(item["error"])
        filesystems.append(item)
    return filesystems, _select_error(errors)


def _physical_disk_ids_for_report(
    smart_by_id, block_graph, filesystems, include_topology_inventory=True
):
    """Select the bounded disk inventory without orphaning probe relations.

    Filesystem probes are an explicit operator request. Their resolved backing
    disks therefore take precedence over unobserved topology-only inventory
    entries, while explicitly queried SMART disks retain their highest
    priority. The wire contract has a hard maximum, so any relationship that
    cannot fit is removed rather than sending an invalid reference that would
    make the server reject the complete hardware domain.
    """
    nodes = block_graph.get("nodes", {}) if isinstance(block_graph, dict) else {}
    def excluded(disk_id):
        return str(disk_id).lower().startswith("zram")

    def supported_topology_device(disk_id, node):
        if excluded(disk_id) or node.get("type") != "disk":
            return False
        return disk_id == "synoboot" or str(node.get("transport") or "").lower() == "usb"

    selected = [disk_id for disk_id in smart_by_id if not excluded(disk_id)]
    selected_set = set(selected)

    for filesystem in filesystems:
        for disk_id in filesystem.get("backing_disk_ids", []):
            if (
                disk_id not in selected_set
                and nodes.get(disk_id, {}).get("type") == "disk"
                and not excluded(disk_id)
            ):
                selected.append(disk_id)
                selected_set.add(disk_id)

    if include_topology_inventory:
        for disk_id, node in nodes.items():
            if (
                node.get("type") == "disk"
                and disk_id not in selected_set
                and not excluded(disk_id)
            ):
                selected.append(disk_id)
                selected_set.add(disk_id)
    else:
        # A bounded Device v2 SMART allowlist must not become host-wide
        # inventory. Keep only the operator-visible removable and boot media
        # that are part of the device's storage topology.
        for disk_id, node in nodes.items():
            if disk_id not in selected_set and supported_topology_device(disk_id, node):
                selected.append(disk_id)
                selected_set.add(disk_id)

    selected = selected[:MAX_PHYSICAL_DISKS]
    selected_set = set(selected)
    for filesystem in filesystems:
        filesystem["backing_disk_ids"] = [
            disk_id
            for disk_id in filesystem.get("backing_disk_ids", [])
            if disk_id in selected_set
        ]
    return selected


def _smart_collection_status(smart, error):
    if smart is not None and error is None:
        return "healthy"
    if smart is not None and error and error.get("code") == "smart_return_status_unavailable":
        return "partial"
    if smart is not None:
        return "invalid_data"
    return "unavailable"


def _physical_disk_record(disk_id, smart=None, smart_error=None, graph_node=None):
    graph_node = graph_node or {}
    # When a controller SMART target (for example /dev/nvme0) was reconciled
    # to a namespace disk, render the topology device.  The SMART source is
    # preserved separately, and the physical record remains joinable with
    # filesystem backing_disk_ids.
    device = "/dev/" + disk_id if graph_node else (smart.get("device") if smart else "/dev/" + disk_id)
    return {
        "id": _nullable_text(disk_id, MAX_DISK_DEVICE_LENGTH),
        "device": _nullable_text(device, MAX_DISK_DEVICE_LENGTH),
        "model": _nullable_text(
            smart.get("model") if smart else graph_node.get("model"), MAX_DISK_MODEL_LENGTH
        ),
        "capacity_bytes": (
            smart.get("capacity_bytes") if smart and smart.get("capacity_bytes") is not None
            else (graph_node.get("size") if _valid_counter(graph_node.get("size")) else None)
        ),
        "temperature_c": float(smart["current"]) if smart and smart.get("current") is not None else None,
        "smart_status": smart.get("health", "unknown") if smart else "unknown",
        "power_on_hours": smart.get("hours") if smart else None,
        "written_bytes": smart.get("written_bytes") if smart else None,
        "read_bytes": smart.get("read_bytes") if smart else None,
        "smart_source": _nullable_text(smart.get("source"), MAX_DISK_SMART_SOURCE_LENGTH) if smart else None,
        "completeness": smart.get("completeness") if smart else "unavailable",
        "health_source": smart.get("health_source") if smart else "unknown",
        "native_status": smart.get("native_status") if smart else "unknown",
        "collection_status": _smart_collection_status(smart, smart_error),
        "error": smart_error,
    }


def _storage_summary(physical_disks, filesystems):
    statuses = [disk.get("smart_status") for disk in physical_disks]
    temperatures = [disk.get("temperature_c") for disk in physical_disks if disk.get("temperature_c") is not None]
    return {
        "physical_disk_count": len(physical_disks),
        "smart_passed": sum(status == "passed" for status in statuses),
        "smart_failed": sum(status == "failed" for status in statuses),
        "smart_unknown": sum(status not in {"passed", "failed"} for status in statuses),
        "temperature_min_c": min(temperatures) if temperatures else None,
        "temperature_max_c": max(temperatures) if temperatures else None,
        "filesystem_count": len(filesystems),
    }


def preferred_filesystem_usage(hardware):
    """Return the largest healthy configured filesystem as decimal MB.

    Device-v2's legacy-compatible top-level HDD counters are used by the
    overview cards.  Inside a container, a generic mount scan can include the
    client root filesystem or an operator's small system volume.  Prefer the
    largest *explicitly configured* healthy filesystem from the hardware
    domain instead.  This keeps the overview aligned with the detailed storage
    view without discovering or reading arbitrary host mounts.

    ``None`` means that the hardware collector has not produced a suitable
    filesystem yet, so callers must retain their existing compatibility
    counters.
    """
    if not isinstance(hardware, dict):
        return None
    storage = hardware.get("storage")
    if not isinstance(storage, dict):
        return None
    candidates = []
    for filesystem in storage.get("filesystems") or []:
        if not isinstance(filesystem, dict):
            continue
        if filesystem.get("collection_status") != "healthy":
            continue
        total = filesystem.get("total_bytes")
        used = filesystem.get("used_bytes")
        if not isinstance(total, int) or not isinstance(used, int):
            continue
        if total <= 0 or used < 0 or used > total:
            continue
        candidates.append((total, used))
    if not candidates:
        return None
    total, used = max(candidates, key=lambda item: item[0])
    # The established wire counters are decimal megabytes.  Retain that unit
    # so existing Server validation and clients remain compatible.
    return total // 1000 // 1000, used // 1000 // 1000


def _aggregate_smart_status(records):
    if any(smart and smart.get("health") == "failed" for _, smart, _ in records):
        return "failed"
    if records and all(
        smart is not None and smart.get("health") == "passed" and (
            error is None or error.get("code") == "smart_return_status_unavailable"
        )
        for _, smart, error in records
    ):
        return "passed"
    return "unknown"


def _legacy_smart_record(records, primary_smart_device):
    successful = [smart for _, smart, _ in records if smart is not None]
    if primary_smart_device:
        for _, smart, _ in records:
            if smart and smart.get("device") == primary_smart_device:
                return smart
        return None
    return successful[0] if len(successful) == 1 else None


def _select_error(errors):
    errors = [item for item in errors if item]
    if not errors:
        return None
    if len(errors) == 1:
        return errors[0]
    return _error(
        "partial_failure",
        "One or more extension sources are unavailable",
        "host-collector",
        any(item.get("retryable") for item in errors),
    )


def _topology_disk_id(candidate, block_graph):
    """Map a SMART controller target to one unambiguous topology disk."""
    disk_id = _block_name(candidate)
    nodes = block_graph.get("nodes", {}) if isinstance(block_graph, dict) else {}
    if disk_id in nodes:
        return disk_id
    # smartctl can target /dev/nvme0 while lsblk exposes nvme0n1.  Only map a
    # controller to a namespace when there is exactly one; multiple namespaces
    # are ambiguous and must not inherit one another's SMART observation.
    if disk_id and re.fullmatch(r"nvme\d+", disk_id):
        namespaces = sorted(
            name for name, node in nodes.items()
            if node.get("type") == "disk" and re.fullmatch(re.escape(disk_id) + r"n\d+", name)
        )
        if len(namespaces) == 1:
            return namespaces[0]
    return disk_id


def collect_hardware(
    cpu_model,
    identity_errors=None,
    hwmon_root="/sys/class/hwmon",
    smart_device="auto",
    command_runner=None,
    now=None,
    smart_devices=None,
    primary_smart_device=None,
    filesystem_probes=None,
    system_identity=None,
    sys_block_root="/sys/class/block",
    statvfs_func=None,
    cpu_details=None,
    cpu_stat_path="/proc/stat",
    cpu_usage_sleep=None,
    meminfo_path="/proc/meminfo",
):
    errors = list(identity_errors or [])
    cpu_usage, cpu_usage_error = collect_cpu_usage(cpu_stat_path, cpu_usage_sleep)
    memory_details, memory_error = collect_memory_details(meminfo_path)
    for item in (cpu_usage_error, memory_error):
        if item:
            errors.append(item)
    sensors = collect_hwmon_temperatures(hwmon_root)
    cpu_temperature = pick_cpu_temperature(sensors)
    if not cpu_temperature:
        errors.append(
            _error("hwmon_unavailable", "CPU temperature is unavailable", "hwmon", True)
        )
    configured_smart_devices = smart_device if smart_devices is None else smart_devices
    smart_records, smart_error = collect_smart_devices(configured_smart_devices, command_runner)
    if smart_error:
        errors.append(smart_error)

    block_graph, graph_error = collect_block_device_graph(command_runner, sys_block_root)
    filesystems, filesystems_error = collect_filesystems(
        filesystem_probes, block_graph, command_runner, statvfs_func
    )

    smart_by_id = {}
    for candidate, smart, record_error in smart_records:
        disk_id = _topology_disk_id(candidate, block_graph)
        if disk_id and disk_id not in smart_by_id:
            smart_by_id[disk_id] = (smart, record_error)
    physical_ids = _physical_disk_ids_for_report(
        smart_by_id,
        block_graph,
        filesystems,
        # A non-empty Device v2 SMART allowlist is an authorization boundary:
        # do not turn a narrow set of mapped block devices into a host-wide
        # topology inventory.  An empty allowlist deliberately requests the
        # existing topology-only view, and automatic discovery retains the
        # broad compatibility behavior.
        include_topology_inventory=not (
            isinstance(configured_smart_devices, (list, tuple))
            and len(configured_smart_devices) > 0
        ),
    )
    physical_disks = []
    for disk_id in physical_ids:
        smart, record_error = smart_by_id.get(disk_id, (None, None))
        record = _physical_disk_record(
            disk_id, smart, record_error, block_graph["nodes"].get(disk_id)
        )
        if smart is None and record_error is None:
            record["collection_status"] = "unsupported"
        physical_disks.append(record)
    physical_disks.sort(key=lambda record: record.get("id") or "")

    legacy_smart = _legacy_smart_record(smart_records, primary_smart_device)
    storage_error = _select_error([smart_error, graph_error, filesystems_error])
    timestamp = _utc_timestamp(now)
    disk_temperature = None
    if legacy_smart and legacy_smart.get("current") is not None:
        disk_temperature = {
            "current": float(legacy_smart["current"]),
            "highest": float(legacy_smart["highest"]) if legacy_smart.get("highest") is not None else None,
            "lowest": float(legacy_smart["lowest"]) if legacy_smart.get("lowest") is not None else None,
            "unit": "C",
            "source": _nullable_text(legacy_smart.get("temperature_source"), MAX_TEMPERATURE_SOURCE_LENGTH),
        }

    reported_cpu_details = dict(cpu_details) if isinstance(cpu_details, dict) else None
    if reported_cpu_details is not None:
        reported_cpu_details["usage"] = cpu_usage
    return {
        "cpu_model": _nullable_text(cpu_model, MAX_CPU_MODEL_LENGTH),
        "cpu_details": reported_cpu_details,
        "memory_details": memory_details,
        "cpu_temperature": {
            "value": float(cpu_temperature["value"]),
            "unit": "C",
            "label": _nullable_text(cpu_temperature.get("label"), MAX_TEMPERATURE_SOURCE_LENGTH),
            "source": _nullable_text(cpu_temperature.get("source"), MAX_TEMPERATURE_SOURCE_LENGTH),
        } if cpu_temperature else None,
        "disk_temperature": disk_temperature,
        "disk_smart_status": _aggregate_smart_status(smart_records),
        "disk_power_on_hours": legacy_smart.get("hours") if legacy_smart else None,
        "disk_written_bytes": legacy_smart.get("written_bytes") if legacy_smart else None,
        "disk_read_bytes": legacy_smart.get("read_bytes") if legacy_smart else None,
        "disk_device": _nullable_text(legacy_smart.get("device"), MAX_DISK_DEVICE_LENGTH) if legacy_smart else None,
        "disk_smart_source": _nullable_text(legacy_smart.get("source"), MAX_DISK_SMART_SOURCE_LENGTH) if legacy_smart else None,
        "storage": {
            "physical_disks": physical_disks,
            "filesystems": filesystems,
            "summary": _storage_summary(physical_disks, filesystems),
            "updated_at": timestamp,
            "stale": False,
            "error": storage_error,
        },
        "system_identity": system_identity,
        "updated_at": timestamp,
        "stale": False,
        "error": _select_error(errors),
    }


def _format_ports(ports):
    values = []
    for port in ports or []:
        if not isinstance(port, dict):
            continue
        private = port.get("PrivatePort")
        public = port.get("PublicPort")
        protocol = port.get("Type") or "tcp"
        address = port.get("IP") or "0.0.0.0"
        if public and private:
            values.append("%s:%s->%s/%s" % (address, public, private, protocol))
        elif private:
            values.append("%s/%s" % (private, protocol))
    return ", ".join(values) or "-"


def _docker_request(socket_path, path, timeout=DOCKER_TIMEOUT_SECONDS):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(timeout)
        connection.connect(socket_path)
        request = "GET %s HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n" % path
        connection.sendall(request.encode("ascii"))
        chunks = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(len(item) for item in chunks) > MAX_DOCKER_RESPONSE_BYTES:
                raise ValueError("Docker response exceeds the allowed size")
    finally:
        connection.close()
    raw = b"".join(chunks)
    header, separator, body = raw.partition(b"\r\n\r\n")
    if not separator:
        raise ValueError("invalid Docker response")
    status_line = header.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    parts = status_line.split()
    if len(parts) < 2 or not parts[1].isdigit():
        raise ValueError("invalid Docker response")
    status = int(parts[1])
    if status < 200 or status >= 300:
        error = RuntimeError("Docker API returned an error")
        error.http_status = status
        raise error
    headers = header.decode("iso-8859-1", errors="replace").lower()
    if "transfer-encoding: chunked" in headers:
        decoded = []
        position = 0
        while True:
            end = body.find(b"\r\n", position)
            if end < 0:
                raise ValueError("invalid Docker response")
            size = int(body[position:end].split(b";", 1)[0], 16)
            position = end + 2
            if size == 0:
                break
            decoded.append(body[position:position + size])
            position += size + 2
        body = b"".join(decoded)
    return json.loads(body.decode("utf-8"))


def collect_docker(
    socket_path="/var/run/docker.sock",
    container_limit=0,
    request_func=None,
    now=None,
):
    request = request_func or (lambda path: _docker_request(socket_path, path))
    try:
        rows = request("/containers/json?all=1")
        if not isinstance(rows, list):
            raise ValueError("Docker response is not a list")
    except Exception as exc:
        status = getattr(exc, "http_status", None)
        return {
            "running": 0,
            "total": 0,
            "limit": min(max(0, int(container_limit or 0)), MAX_DOCKER_CONTAINERS),
            "truncated": False,
            "containers": [],
            "updated_at": None,
            "stale": True,
            "error": _error(
                "docker_unavailable",
                "Docker data is unavailable",
                "docker-collector",
                True,
                status if isinstance(status, int) and 100 <= status <= 599 else None,
            ),
        }

    configured_limit = min(max(0, int(container_limit or 0)), MAX_DOCKER_CONTAINERS)
    if len(rows) > MAX_DOCKER_COUNT:
        return {
            "running": 0,
            "total": 0,
            "limit": configured_limit,
            "truncated": False,
            "containers": [],
            "updated_at": None,
            "stale": True,
            "error": _error(
                "docker_response_too_large",
                "Docker data exceeds the allowed size",
                "docker-collector",
                False,
            ),
        }
    effective_limit = configured_limit or MAX_DOCKER_CONTAINERS
    selected = rows[:effective_limit]
    containers = []
    for row in selected:
        if not isinstance(row, dict):
            continue
        names = ", ".join(str(name).lstrip("/") for name in (row.get("Names") or []))
        containers.append(
            {
                "names": _truncate(names, MAX_DOCKER_NAME_LENGTH),
                "image": _truncate(row.get("Image"), MAX_DOCKER_IMAGE_LENGTH),
                "status": _truncate(row.get("Status"), MAX_DOCKER_STATUS_LENGTH),
                "ports": _truncate(_format_ports(row.get("Ports")), MAX_DOCKER_PORTS_LENGTH),
            }
        )
    total = len(rows)
    return {
        "running": sum(1 for row in rows if isinstance(row, dict) and row.get("State") == "running"),
        "total": total,
        "limit": configured_limit,
        "truncated": len(containers) < total,
        "containers": containers,
        "updated_at": _utc_timestamp(now),
        "stale": False,
        "error": None,
    }


def atomic_write_json(path, payload):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".snapshot-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class HostExtensionCollector(object):
    def __init__(
        self,
        host_os_release_file=None,
        hwmon_root=None,
        smart_device=None,
        smart_devices=None,
        primary_smart_device=None,
        filesystem_probes=None,
        dsm_version_file=None,
        client_build=None,
        collect_build_metadata=True,
        sys_block_root=None,
        docker_socket=None,
        hardware_interval=None,
        docker_interval=None,
        docker_container_limit=None,
        hermes_status_file=None,
        hermes_export_enabled=None,
        hermes_snapshot_interval=None,
        status_dir=None,
        command_runner=None,
        docker_request=None,
        lucky_collector=None,
        lucky_interval=None,
        easytier_collector=None,
        easytier_interval=None,
        easytier_args=None,
        unifi_collector=None,
        unifi_interval=None,
    ):
        self.host_os_release_file = host_os_release_file or os.getenv(
            "HOST_OS_RELEASE_FILE", "/host/etc/os-release"
        )
        self.hwmon_root = hwmon_root or os.getenv("HWMON_ROOT", "/sys/class/hwmon")
        self.smart_device = smart_device or os.getenv("SMART_DEVICE", "auto")
        if smart_devices is None:
            smart_devices = parse_smart_devices_value(os.getenv("SMART_DEVICES"))
        self.smart_devices = self.smart_device if smart_devices is None else smart_devices
        self.primary_smart_device = primary_smart_device or os.getenv("PRIMARY_SMART_DEVICE")
        self.filesystem_probes = list(filesystem_probes or [])[:MAX_FILESYSTEMS]
        self.dsm_version_file = dsm_version_file or os.getenv(
            "DSM_VERSION_FILE", "/host/etc.defaults/VERSION"
        )
        self.client_build = client_build if client_build is not None else (
            collect_client_build() if collect_build_metadata else None
        )
        self.sys_block_root = sys_block_root or os.getenv("SYS_BLOCK_ROOT", "/sys/class/block")
        self.docker_socket = docker_socket or os.getenv(
            "DOCKER_SOCKET", "/var/run/docker.sock"
        )
        self.hardware_interval = hardware_interval or _env_int("HARDWARE_INTERVAL", 600)
        self.docker_interval = docker_interval or _env_int("DOCKER_INTERVAL", 60)
        if docker_container_limit is None:
            docker_container_limit = _env_int("DOCKER_CONTAINER_LIMIT", 0, 0)
        self.docker_container_limit = min(max(0, docker_container_limit), MAX_DOCKER_CONTAINERS)
        self.hermes_status_file = hermes_status_file or os.getenv(
            "HERMES_STATUS_FILE", "/var/lib/serverstatus-client/hermes/hermes.json"
        )
        self.hermes_export_enabled = _env_bool("HERMES_EXPORT_ENABLED", True) if hermes_export_enabled is None else bool(hermes_export_enabled)
        self.hermes_snapshot_interval = hermes_snapshot_interval or _env_int(
            "HERMES_SNAPSHOT_INTERVAL", 10
        )
        self.status_dir = status_dir if status_dir is not None else os.getenv(
            "CLIENT_STATUS_DIR", "/var/lib/serverstatus-client"
        )
        self.command_runner = command_runner
        self.docker_request = docker_request
        self.lucky_collector = lucky_collector or collector_from_environment()
        self.lucky_interval = lucky_interval or _env_int("LUCKY_INTERVAL", 600)
        self.easytier_collector = easytier_collector or easytier_collector_from_environment(easytier_args)
        if easytier_interval is None:
            resolved_config = getattr(self.easytier_collector, "config", {})
            self.easytier_interval = resolved_config.get(
                "interval_seconds", _env_int("EASYTIER_INTERVAL_SECONDS", 30)
            )
        else:
            self.easytier_interval = easytier_interval
        self.unifi_collector = unifi_collector
        self.unifi_interval = int(unifi_interval or getattr(unifi_collector, "config", None) and unifi_collector.config.interval_seconds or 60)
        self.host_os, os_error = collect_host_os(self.host_os_release_file)
        self.system_identity = collect_system_identity(
            self.host_os_release_file, self.dsm_version_file
        )
        if self.system_identity.get("pretty_name"):
            self.host_os = self.system_identity["pretty_name"]
        self.cpu_model, cpu_error = collect_cpu_model(command_runner)
        self.cpu_details, _cpu_details_error = collect_cpu_details(command_runner)
        # CPU detail fields are an optional observability enhancement. Their
        # absence must not turn otherwise valid SMART/storage data into a
        # failed hardware domain.
        # DSM normally exposes /etc.defaults/VERSION instead of os-release.
        # Its validated identity is authoritative, so a missing os-release
        # mount is expected and must not degrade an otherwise healthy hardware
        # report.
        dsm_identity = self.system_identity.get("source") == "dsm-version"
        self.identity_errors = [
            item for item in (os_error, cpu_error)
            if item and not (dsm_identity and item.get("code") == "host_os_unavailable")
        ]
        self._hardware = not_reported_hardware()
        self._docker = not_reported_docker()
        self._hermes = not_reported_hermes()
        self._lucky = not_configured_lucky()
        self._easytier = not_configured_easytier()
        self._unifi = not_collected_unifi(unifi_collector.config.profile_id) if unifi_collector is not None else not_configured_unifi()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._started = False

    def _store(self, domain, payload):
        with self._lock:
            setattr(self, "_" + domain, copy.deepcopy(payload))
        if self.status_dir:
            try:
                atomic_write_json(os.path.join(self.status_dir, domain + ".json"), payload)
            except OSError:
                pass

    def collect_hardware_once(self):
        try:
            payload = collect_hardware(
                self.cpu_model,
                identity_errors=self.identity_errors,
                hwmon_root=self.hwmon_root,
                smart_device=self.smart_device,
                command_runner=self.command_runner,
                smart_devices=self.smart_devices,
                primary_smart_device=self.primary_smart_device,
                filesystem_probes=self.filesystem_probes,
                system_identity=self.system_identity,
                sys_block_root=self.sys_block_root,
                cpu_details=self.cpu_details,
            )
        except Exception:
            payload = not_reported_hardware()
            payload["error"] = _error(
                "source_error",
                "Extension data is unavailable",
                "host-collector",
                True,
            )
        self._store("hardware", payload)
        return payload

    def collect_docker_once(self):
        try:
            payload = collect_docker(
                self.docker_socket,
                self.docker_container_limit,
                self.docker_request,
            )
        except Exception:
            payload = not_reported_docker()
            payload["error"] = _error(
                "source_error",
                "Extension data is unavailable",
                "docker-collector",
                True,
            )
        self._store("docker", payload)
        return payload

    def collect_hermes_once(self):
        payload = read_hermes_snapshot(self.hermes_status_file, self.hermes_export_enabled)
        self._store("hermes", payload)
        return payload

    def collect_lucky_once(self):
        try:
            payload = self.lucky_collector.collect()
        except Exception:
            payload = not_configured_lucky()
            payload["status"] = "unavailable"
            payload["error"] = _error(
                "internal_error",
                "Lucky data is unavailable",
                "lucky-collector",
                True,
            )
        self._store("lucky", payload)
        return payload

    def collect_easytier_once(self):
        try:
            payload = self.easytier_collector.collect()
        except Exception:
            payload = not_configured_easytier()
            payload["status"] = "unavailable"
            payload["error"] = _error(
                "source_error",
                "EasyTier data is unavailable",
                "easytier-collector",
                True,
            )
        self._store("easytier", payload)
        return payload

    def collect_unifi_once(self):
        if self.unifi_collector is None:
            payload = not_configured_unifi()
        else:
            try:
                payload = self.unifi_collector.collect()
            except Exception:
                payload = not_collected_unifi(self.unifi_collector.config.profile_id)
                payload["transport"]["status"] = "unavailable"
                payload["error"] = _error("collector_failure", "UniFi observation is unavailable", "unifi", True)
        self._store("unifi", payload)
        return payload

    def _run_periodically(self, function, interval, initial_delay=False):
        if initial_delay and self._stop.wait(interval):
            return
        while not self._stop.is_set():
            try:
                function()
            except Exception:
                pass
            self._stop.wait(interval)

    def start(self):
        if self._started:
            return
        self._started = True
        tasks = (
            (self.collect_hardware_once, self.hardware_interval, "hardware-collector"),
            (self.collect_docker_once, self.docker_interval, "docker-collector"),
            (self.collect_hermes_once, self.hermes_snapshot_interval, "hermes-snapshot-reader"),
            (self.collect_lucky_once, self.lucky_interval, "lucky-collector"),
            (self.collect_easytier_once, self.easytier_interval, "easytier-collector"),
        )
        unifi_task = (self.collect_unifi_once, self.unifi_interval, "unifi-collector") if self.unifi_collector is not None else None
        # Device v2 can send an update immediately after start(). Populate every
        # independent domain synchronously first so a fresh container never
        # publishes a partially initialised extension snapshot.
        for function, _, _ in tasks:
            try:
                function()
            except Exception:
                pass
        for function, interval, name in tasks + ((unifi_task,) if unifi_task else ()):
            thread = threading.Thread(
                target=self._run_periodically,
                args=(function, interval, True),
                name=name,
            )
            thread.daemon = True
            thread.start()

    def stop(self):
        self._stop.set()

    def extension_payload(self):
        with self._lock:
            hardware = copy.deepcopy(self._hardware)
            docker_stats = copy.deepcopy(self._docker)
            hermes = copy.deepcopy(self._hermes)
            lucky = copy.deepcopy(self._lucky)
            easytier = copy.deepcopy(self._easytier)
            unifi = copy.deepcopy(self._unifi)
        payload = {
            "extension_version": EXTENSION_VERSION,
            "hardware": hardware,
            "docker": docker_stats,
            "hermes": hermes,
            "lucky": lucky,
            "easytier": easytier,
            "unifi": unifi,
        }
        # Build provenance is optional.  Older/legacy clients must omit this
        # domain instead of sending JSON null, which strict Device v2 decoding
        # correctly treats as an invalid object.
        if self.client_build is not None:
            payload["client_build"] = copy.deepcopy(self.client_build)
        return payload

    def preferred_disk_usage(self, fallback_total, fallback_used):
        """Return overview disk counters, preferring authorized storage data."""
        with self._lock:
            hardware = copy.deepcopy(self._hardware)
        selected = preferred_filesystem_usage(hardware)
        return selected if selected is not None else (fallback_total, fallback_used)


def add_extension_payload(update, collector):
    try:
        update.update(collector.extension_payload())
    except Exception:
        update.update(
            {
                "extension_version": EXTENSION_VERSION,
                "hardware": not_reported_hardware(),
                "docker": not_reported_docker(),
                "hermes": not_reported_hermes(),
                "lucky": not_configured_lucky(),
                "easytier": not_configured_easytier(),
                "unifi": not_configured_unifi(),
            }
        )
    return update
