#!/usr/bin/env python3
# coding: utf-8
# Update by : https://github.com/cppla/ServerStatus, Update date: 20250902
# 依赖于psutil跨平台库
# 版本：1.1.0, 支持Python版本：3.6+
# 支持操作系统： Linux, Windows, OSX, Sun Solaris, FreeBSD, OpenBSD and NetBSD, both 32-bit and 64-bit architectures
# 说明: 默认情况下修改server和user就可以了。丢包率监测方向可以自定义，例如：CU = "www.facebook.com"。

SERVER = ""
USER = ""


PASSWORD = "USER_DEFAULT_PASSWORD"
PORT = 35601
CU = "cu.tz.cloudcpp.com"
CT = "ct.tz.cloudcpp.com"
CM = "cm.tz.cloudcpp.com"
PROBEPORT = 80
PROBE_PROTOCOL_PREFER = "ipv4"  # ipv4, ipv6
PING_PACKET_HISTORY_LEN = 100
INTERVAL = 1

import socket
import time
import timeit
import os
import sys
import json
import errno
import psutil
import threading
import platform
import glob
import subprocess
import re
from queue import Queue

def _env_str(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value

def _env_int(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default

def _load_export_config():
    path = os.getenv("HERMES_EXPORT_CONFIG", "/app/hermes-exporter.json")
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _config_str(config, key, env_name, default):
    defaults = config.get("defaults") if isinstance(config.get("defaults"), dict) else {}
    value = defaults.get(key)
    if value is None or str(value).strip() == "":
        value = config.get(key)
    if value is None or str(value).strip() == "":
        return _env_str(env_name, default)
    return str(value)

# Allow docker env overrides. 优先级：运行程序传递参数 > 用户修改的USER > Docker/系统
SERVER = _env_str("SERVER", SERVER) if SERVER == "" else SERVER
USER = _env_str("SERVERSTATUS_USER", _env_str("USER", USER)) if USER == "" else USER
PASSWORD = _env_str("PASSWORD", PASSWORD)
PORT = _env_int("PORT", PORT)
INTERVAL = _env_int("INTERVAL", INTERVAL)
PROBEPORT = _env_int("PROBEPORT", PROBEPORT)
PROBE_PROTOCOL_PREFER = _env_str("PROBE_PROTOCOL_PREFER", PROBE_PROTOCOL_PREFER)
PING_PACKET_HISTORY_LEN = _env_int("PING_PACKET_HISTORY_LEN", PING_PACKET_HISTORY_LEN)
CU = _env_str("CU", CU)
CT = _env_str("CT", CT)
CM = _env_str("CM", CM)
HERMES_EXPORT_CONFIG_DATA = _load_export_config()
HERMES_STATUS_DIR = _config_str(HERMES_EXPORT_CONFIG_DATA, "status_dir", "HERMES_STATUS_DIR", "/hermes/status")
HARDWARE_STATUS_FILE = _config_str(HERMES_EXPORT_CONFIG_DATA, "hardware_status_file", "HARDWARE_STATUS_FILE", os.path.join(HERMES_STATUS_DIR, "hardware.json"))
HOST_OS_RELEASE_FILE = _env_str("HOST_OS_RELEASE_FILE", "/host/etc/os-release")
SMART_DEVICE = _env_str("SMART_DEVICE", "auto")
DOCKER_SOCKET = _env_str("DOCKER_SOCKET", "/var/run/docker.sock")
DOCKER_CONTAINER_LIMIT = _env_int("DOCKER_CONTAINER_LIMIT", 0)
DOCKER_JSON_MAX_BYTES = _env_int("DOCKER_JSON_MAX_BYTES", 12000)
HERMES_JSON_MAX_BYTES = _env_int("HERMES_JSON_MAX_BYTES", 12000)

def _read_os_release(path):
    values = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except Exception:
        return {}
    return values

def get_host_os_name():
    for path in (HOST_OS_RELEASE_FILE, "/etc/os-release"):
        info = _read_os_release(path)
        if not info:
            continue
        if info.get("PRETTY_NAME"):
            return info["PRETTY_NAME"]
        name = info.get("NAME") or info.get("ID")
        version = info.get("VERSION_ID") or info.get("VERSION")
        if name and version:
            return "%s %s" % (name, version)
        if name:
            return name

    try:
        sysname = platform.system()
        release = platform.release()
        return " ".join([part for part in (sysname, release) if part]) or "unknown"
    except Exception:
        return "unknown"

CPU_MODEL_CACHE = None

def _cpu_model_from_lscpu(data):
    if not isinstance(data, dict):
        return ""
    for item in data.get("lscpu") or []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip().rstrip(":").lower()
        if field == "model name":
            return str(item.get("data") or "").strip()
    return ""

def get_cpu_model():
    global CPU_MODEL_CACHE
    if CPU_MODEL_CACHE is not None:
        return CPU_MODEL_CACHE
    model = ""
    try:
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        proc = subprocess.run(
            ["lscpu", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
            env=env,
        )
        if proc.returncode == 0 and proc.stdout:
            model = _cpu_model_from_lscpu(json.loads(proc.stdout))
    except Exception:
        pass
    if not model:
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.lower().startswith("model name") and ":" in line:
                        model = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass
    CPU_MODEL_CACHE = model or "unknown"
    return CPU_MODEL_CACHE

def get_uptime():
    return int(time.time() - psutil.boot_time())

def get_memory():
    Mem = psutil.virtual_memory()
    return int(Mem.total / 1024.0), int(Mem.used / 1024.0)

def get_swap():
    Mem = psutil.swap_memory()
    return int(Mem.total/1024.0), int(Mem.used/1024.0)

def get_hdd():
    if "darwin" in sys.platform:
        return int(psutil.disk_usage("/").total/1024.0/1024.0), int((psutil.disk_usage("/").total-psutil.disk_usage("/").free)/1024.0/1024.0)
    else:
        valid_fs = ["ext4", "ext3", "ext2", "reiserfs", "jfs", "btrfs", "fuseblk", "zfs", "simfs", "ntfs", "fat32",
                    "exfat", "xfs"]
        disks = dict()
        size = 0
        used = 0
        for disk in psutil.disk_partitions():
            if not disk.device in disks and disk.fstype.lower() in valid_fs:
                disks[disk.device] = disk.mountpoint
        for disk in disks.values():
            usage = psutil.disk_usage(disk)
            size += usage.total
            used += usage.used
        return int(size/1024.0/1024.0), int(used/1024.0/1024.0)

def get_cpu():
    return psutil.cpu_percent(interval=INTERVAL)

def liuliang():
    NET_IN = 0
    NET_OUT = 0
    net = psutil.net_io_counters(pernic=True)
    for k, v in net.items():
        if 'lo' in k or 'tun' in k \
                or 'docker' in k or 'veth' in k \
                or 'br-' in k or 'vmbr' in k \
                or 'vnet' in k or 'kube' in k:
            continue
        else:
            NET_IN += v[1]
            NET_OUT += v[0]
    return NET_IN, NET_OUT

def tupd():
    '''
    tcp, udp, process, thread count: for view ddcc attack , then send warning
    :return:
    '''
    try:
        if sys.platform.startswith("linux") is True:
            t = int(os.popen('ss -t|wc -l').read()[:-1])-1
            u = int(os.popen('ss -u|wc -l').read()[:-1])-1
            p = int(os.popen('ps -ef|wc -l').read()[:-1])-2
            d = int(os.popen('ps -eLf|wc -l').read()[:-1])-2
        elif sys.platform.startswith("darwin") is True:
            t = int(os.popen('lsof -nP -iTCP  | wc -l').read()[:-1]) - 1
            u = int(os.popen('lsof -nP -iUDP  | wc -l').read()[:-1]) - 1
            p = len(psutil.pids())
            d = 0
            for k in psutil.pids():
                try:
                    d += psutil.Process(k).num_threads()
                except:
                    pass

        elif sys.platform.startswith("win") is True:
            t = int(os.popen('netstat -an|find "TCP" /c').read()[:-1])-1
            u = int(os.popen('netstat -an|find "UDP" /c').read()[:-1])-1
            p = len(psutil.pids())
            # if you find cpu is high, please set d=0
            d = sum([psutil.Process(k).num_threads() for k in psutil.pids()])
        else:
            t,u,p,d = 0,0,0,0
        return t,u,p,d
    except:
        return 0,0,0,0

def get_network(ip_version):
    if(ip_version == 4):
        HOST = "ipv4.google.com"
    elif(ip_version == 6):
        HOST = "ipv6.google.com"
    try:
        socket.create_connection((HOST, 80), 2).close()
        return True
    except:
        return False

lostRate = {
    '10010': 0.0,
    '189': 0.0,
    '10086': 0.0
}
pingTime = {
    '10010': 0,
    '189': 0,
    '10086': 0
}
netSpeed = {
    'netrx': 0.0,
    'nettx': 0.0,
    'clock': 0.0,
    'diff': 0.0,
    'avgrx': 0,
    'avgtx': 0
}
diskIO = {
    'read': 0,
    'write': 0
}
monitorServer = {}

def _json_compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

def _json_compact_limited(value, max_bytes, list_key, empty_value):
    payload = _json_compact(value)
    if len(payload.encode("utf-8")) <= max_bytes:
        return payload
    clipped = dict(value) if isinstance(value, dict) else dict(empty_value)
    rows = list(clipped.get(list_key) or [])
    clipped["truncated"] = True
    while rows:
        clipped[list_key] = rows
        payload = _json_compact(clipped)
        if len(payload.encode("utf-8")) <= max_bytes:
            return payload
        rows = rows[:-1]
    clipped[list_key] = []
    payload = _json_compact(clipped)
    if len(payload.encode("utf-8")) <= max_bytes:
        return payload
    return _json_compact(empty_value)

def _truncate(value, limit):
    text = str(value or "")
    return text if len(text) <= limit else text[:limit - 1] + "…"

def _read_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception:
        return ""

def _hwmon_temperatures():
    sensors = []
    for base in glob.glob("/sys/class/hwmon/hwmon*"):
        chip = _read_file(os.path.join(base, "name")) or os.path.basename(base)
        for temp_path in glob.glob(os.path.join(base, "temp*_input")):
            m = re.search(r"temp(\d+)_input$", temp_path)
            idx = m.group(1) if m else ""
            label = _read_file(os.path.join(base, "temp%s_label" % idx))
            raw = _read_file(temp_path)
            try:
                value = int(raw) / 1000.0
            except Exception:
                continue
            name = " ".join(x for x in [chip, label] if x).strip()
            sensors.append({"name": name or chip, "chip": chip, "label": label, "value": round(value, 1)})
    return sensors

def _pick_temperature(sensors, kind):
    keywords = {
        "cpu": ("coretemp", "cpu", "package", "k10temp"),
        "disk": ("nvme", "drivetemp", "hdd", "ssd", "composite", "disk")
    }.get(kind, ())
    fallback = None
    for sensor in sensors:
        name = (sensor.get("name") or "").lower()
        if fallback is None:
            fallback = sensor
        if any(key in name for key in keywords):
            return sensor
    return fallback

def _smart_candidates():
    if SMART_DEVICE and SMART_DEVICE != "auto":
        parts = SMART_DEVICE.split()
        if "-d" in parts:
            index = parts.index("-d")
            dev = parts[-1]
            typ = parts[index + 1] if index + 1 < len(parts) else ""
            return [(dev, typ)]
        return [(SMART_DEVICE, "")]
    devices = []
    try:
        proc = subprocess.run(["smartctl", "--scan"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=4)
        for line in proc.stdout.splitlines():
            parts = line.split("#", 1)[0].split()
            if not parts:
                continue
            dev = parts[0]
            typ = ""
            if "-d" in parts:
                index = parts.index("-d")
                if index + 1 < len(parts):
                    typ = parts[index + 1]
            if dev.startswith("/dev/") and (dev, typ) not in devices:
                devices.append((dev, typ))
    except Exception:
        pass
    for part in psutil.disk_partitions(all=False):
        dev = part.device or ""
        if dev.startswith("/dev/"):
            dev = re.sub(r"p?\d+$", "", dev)
            if (dev, "") not in devices:
                devices.append((dev, ""))
    for pattern in ("/dev/nvme*n1", "/dev/sd?", "/dev/vd?"):
        for dev in glob.glob(pattern):
            if (dev, "") not in devices:
                devices.append((dev, ""))
    return devices

def _run_smartctl():
    for dev, typ in _smart_candidates():
        type_variants = [""]
        if typ:
            type_variants.append(typ)
        for use_type in type_variants:
            typed_args = ["-d", use_type] if use_type else []
            data = {}
            source = ""
            text = ""
            text_source = ""
            for cmd in (
                ["sudo", "-n", "smartctl", "-x"] + typed_args + [dev],
                ["smartctl", "-x"] + typed_args + [dev],
                ["sudo", "-n", "smartctl", "-a"] + typed_args + [dev],
                ["smartctl", "-a"] + typed_args + [dev],
            ):
                try:
                    proc = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=8
                    )
                    if "START OF READ SMART DATA SECTION" in proc.stdout or "SMART overall-health" in proc.stdout:
                        text = proc.stdout
                        text_source = " ".join(cmd)
                        break
                except Exception:
                    continue
            for cmd in (
                ["sudo", "-n", "smartctl", "-x", "-j"] + typed_args + [dev],
                ["smartctl", "-x", "-j"] + typed_args + [dev],
                ["sudo", "-n", "smartctl", "-a", "-j"] + typed_args + [dev],
                ["smartctl", "-a", "-j"] + typed_args + [dev],
            ):
                try:
                    proc = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=8
                    )
                    if not proc.stdout:
                        continue
                    parsed = json.loads(proc.stdout)
                    if isinstance(parsed, dict):
                        data = parsed
                        source = " ".join(cmd)
                        break
                except Exception:
                    continue
            if data or text:
                data["_device"] = dev
                data["_device_type"] = use_type
                data["_source"] = source or text_source
                data["_smart_text"] = text
                data["_smart_text_source"] = text_source
                return data
    return {}

def _smart_attribute_raw(text, attr_id, attr_name):
    pattern = re.compile(r"^\s*%d\s+%s\b.*?\s-\s+(-?\d+)" % (attr_id, re.escape(attr_name)), re.I | re.M)
    match = pattern.search(text or "")
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None

def _smart_stat_value(text, page, offset, description):
    pattern = re.compile(
        r"^\s*%s\s+%s\s+\d+\s+(-?\d+)\s+---\s+%s\s*$" % (
            re.escape(page),
            re.escape(offset),
            re.escape(description),
        ),
        re.I | re.M,
    )
    match = pattern.search(text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None

def _smart_temperature_stats(data):
    text = data.get("_smart_text", "")
    current = _smart_stat_value(text, "0x05", "0x008", "Current Temperature")
    highest = _smart_stat_value(text, "0x05", "0x020", "Highest Temperature")
    lowest = _smart_stat_value(text, "0x05", "0x028", "Lowest Temperature")
    if current is None:
        current = _smart_temperature(data)
    return {
        "current": current,
        "highest": highest,
        "lowest": lowest,
    }

def _smart_text_passed(text):
    match = re.search(r"SMART overall-health self-assessment test result:\s*([A-Z]+)", text or "", re.I)
    if not match:
        return None
    return match.group(1).lower() == "passed"

def _run_smartctl_legacy():
    for dev, typ in _smart_candidates():
        typed_args = ["-d", typ] if typ else []
        for cmd in (["smartctl", "-a", "-j"] + typed_args + [dev], ["smartctl", "-a", "-j", dev]):
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=6
                )
                if not proc.stdout:
                    continue
                data = json.loads(proc.stdout)
                data["_device"] = dev
                data["_device_type"] = typ
                return data
            except Exception:
                continue
    return {}

def _first_number(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None

def _nested_number(data, key_names):
    if isinstance(data, dict):
        for key, value in data.items():
            key_l = str(key).lower()
            if key_l in key_names:
                number = _first_number(value)
                if number is not None:
                    return number
            found = _nested_number(value, key_names)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _nested_number(item, key_names)
            if found is not None:
                return found
    return None

def _smart_passed(data):
    text_passed = _smart_text_passed(data.get("_smart_text", ""))
    if text_passed is not None:
        return text_passed
    status = data.get("smart_status") or {}
    if isinstance(status, dict) and isinstance(status.get("passed"), bool):
        return status.get("passed")
    for key in ("smart_health_status", "health_status", "overall_health", "status"):
        value = data.get(key)
        if isinstance(value, str):
            value_l = value.lower()
            if any(word in value_l for word in ("pass", "ok", "healthy")):
                return True
            if any(word in value_l for word in ("fail", "error", "bad")):
                return False
    grown = _nested_number(data, {"scsi_grown_defect_list"})
    if grown is not None:
        return grown == 0
    return None

def _smart_temperature(data):
    temp_194 = _smart_attribute_raw(data.get("_smart_text", ""), 194, "Temperature_Celsius")
    if temp_194 is not None:
        return temp_194
    temp = (data.get("temperature") or {}).get("current")
    if temp is not None:
        return _first_number(temp)
    return _nested_number(data, {
        "current_temperature",
        "temperature_celsius",
        "drive_temperature",
        "temperature_current",
    })

def _smart_power_on_hours(data):
    stat_hours = _smart_stat_value(data.get("_smart_text", ""), "0x01", "0x010", "Power-on Hours")
    if stat_hours is not None:
        return int(stat_hours)
    text_hours = _smart_attribute_raw(data.get("_smart_text", ""), 9, "Power_On_Hours")
    if text_hours is not None:
        return int(text_hours)
    hours = (data.get("power_on_time") or {}).get("hours")
    if hours is not None:
        return int(_first_number(hours))
    found = _nested_number(data, {
        "power_on_hours",
        "power_on_time_hours",
        "accumulated_power_on_hours",
    })
    return int(found) if found is not None else None

def _smart_written_bytes(data):
    stat_lbas = _smart_stat_value(data.get("_smart_text", ""), "0x01", "0x018", "Logical Sectors Written")
    if stat_lbas is not None:
        return int(stat_lbas) * 512
    text_lbas = _smart_attribute_raw(data.get("_smart_text", ""), 241, "Total_LBAs_Written")
    if text_lbas is not None:
        return int(text_lbas) * 512
    nvme = data.get("nvme_smart_health_information_log") or {}
    if isinstance(nvme, dict) and nvme.get("data_units_written") is not None:
        try:
            return int(nvme.get("data_units_written")) * 512000
        except Exception:
            pass
    attrs = ((data.get("ata_smart_attributes") or {}).get("table") or [])
    for item in attrs:
        name = str(item.get("name") or "").lower()
        raw = (item.get("raw") or {}).get("value")
        if raw is None:
            continue
        try:
            raw = int(raw)
        except Exception:
            continue
        if "total_lbas_written" in name:
            return raw * 512
        if "host_writes_32mib" in name:
            return raw * 32 * 1024 * 1024
    scsi = data.get("scsi_error_counter_log") or data.get("scsi_error_counter") or {}
    write = scsi.get("write") if isinstance(scsi, dict) else {}
    if isinstance(write, dict):
        for key, multiplier in (
            ("bytes_processed", 1),
            ("gb_processed", 1000 * 1000 * 1000),
            ("gbytes_processed", 1000 * 1000 * 1000),
            ("blocks_processed", 512),
        ):
            number = _first_number(write.get(key))
            if number is not None:
                return int(number * multiplier)
    return None

def _smart_read_bytes(data):
    stat_lbas = _smart_stat_value(data.get("_smart_text", ""), "0x01", "0x028", "Logical Sectors Read")
    if stat_lbas is not None:
        return int(stat_lbas) * 512
    return None

def _read_status_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _merge_hardware(host_payload, fallback):
    if not isinstance(host_payload, dict):
        return fallback
    merged = dict(fallback or {})
    for key in (
        "cpu_temperature",
        "disk_temperature",
        "disk_smart_status",
        "disk_power_on_hours",
        "disk_written_bytes",
        "disk_read_bytes",
        "disk_device",
        "disk_smart_source",
        "cpu_model",
        "updated_at",
    ):
        value = host_payload.get(key)
        if value is not None and value != "":
            if key == "disk_smart_status":
                current = str(merged.get(key) or "").lower()
                incoming = str(value).lower()
                if incoming == "unknown" and current in ("passed", "failed"):
                    continue
            merged[key] = value
    return merged

def get_hardware_health():
    sensors = _hwmon_temperatures()
    cpu_temp = _pick_temperature(sensors, "cpu")
    disk_temp = _pick_temperature(sensors, "disk")
    smart = _run_smartctl()
    smart_temps = _smart_temperature_stats(smart)
    smart_temp = smart_temps.get("current")
    if smart_temp is not None:
        disk_temp = {
            "name": "%s Device Statistics Temperature" % (smart.get("_device") or "smartctl"),
            "value": float(smart_temp),
            "current": float(smart_temp),
            "highest": float(smart_temps["highest"]) if smart_temps.get("highest") is not None else None,
            "lowest": float(smart_temps["lowest"]) if smart_temps.get("lowest") is not None else None,
        }
    elif not disk_temp and smart.get("temperature", {}).get("current") is not None:
        disk_temp = {
            "name": smart.get("_device", "smartctl"),
            "value": float(smart.get("temperature", {}).get("current"))
        }
    passed = _smart_passed(smart)
    fallback = {
        "cpu_model": get_cpu_model(),
        "cpu_temperature": {
            "value": cpu_temp.get("value"),
            "unit": "C",
            "source": cpu_temp.get("name")
        } if cpu_temp else None,
        "disk_temperature": dict(
            {
                "value": disk_temp.get("value"),
                "unit": "C",
                "source": disk_temp.get("name")
            },
            **{
                key: disk_temp.get(key)
                for key in ("current", "highest", "lowest")
                if disk_temp.get(key) is not None
            }
        ) if disk_temp else None,
        "disk_smart_status": "passed" if passed is True else ("failed" if passed is False else "unknown"),
        "disk_power_on_hours": _smart_power_on_hours(smart),
        "disk_written_bytes": _smart_written_bytes(smart),
        "disk_read_bytes": _smart_read_bytes(smart),
        "disk_device": smart.get("_device"),
        "disk_smart_source": smart.get("_smart_text_source") or smart.get("_source")
    }
    return _merge_hardware(_read_status_json(HARDWARE_STATUS_FILE), fallback)

def _decode_chunked(body):
    out = []
    pos = 0
    while True:
        end = body.find(b"\r\n", pos)
        if end < 0:
            break
        size_text = body[pos:end].split(b";", 1)[0].strip()
        try:
            size = int(size_text, 16)
        except Exception:
            break
        pos = end + 2
        if size == 0:
            break
        out.append(body[pos:pos + size])
        pos += size + 2
    return b"".join(out)

def _http_body(raw):
    header, _, body = raw.partition(b"\r\n\r\n")
    headers = header.decode("iso-8859-1", errors="replace").lower()
    if "transfer-encoding: chunked" in headers:
        return _decode_chunked(body)
    return body

def _docker_request(path):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(3)
        sock.connect(DOCKER_SOCKET)
        req = "GET %s HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n" % path
        sock.sendall(req.encode("ascii"))
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        sock.close()
    body = _http_body(raw)
    return json.loads(body.decode("utf-8", errors="replace"))

def _format_ports(ports):
    if not ports:
        return "-"
    values = []
    for port in ports:
        private = port.get("PrivatePort")
        public = port.get("PublicPort")
        typ = port.get("Type", "tcp")
        ip = port.get("IP", "")
        if public:
            values.append("%s:%s->%s/%s" % (ip or "0.0.0.0", public, private, typ))
        elif private:
            values.append("%s/%s" % (private, typ))
    return ", ".join(values) if values else "-"

def _human_created(epoch):
    try:
        sec = max(0, int(time.time() - int(epoch)))
    except Exception:
        return "-"
    if sec < 120:
        return "%d seconds ago" % sec
    minutes = sec // 60
    if minutes < 120:
        return "%d minutes ago" % minutes
    hours = minutes // 60
    if hours < 48:
        return "%d hours ago" % hours
    days = hours // 24
    if days < 14:
        return "%d days ago" % days
    weeks = days // 7
    if weeks < 9:
        return "%d weeks ago" % weeks
    months = days // 30
    return "%d months ago" % max(1, months)

def get_docker_containers():
    try:
        rows = _docker_request("/containers/json?all=1")
        containers = []
        running = sum(1 for row in rows if (row.get("State") or "") == "running")
        selected_rows = rows if DOCKER_CONTAINER_LIMIT <= 0 else rows[:DOCKER_CONTAINER_LIMIT]
        for row in selected_rows:
            state = row.get("State") or ""
            containers.append({
                "id": _truncate(row.get("Id", "")[:12], 16),
                "image": _truncate(row.get("Image"), 80),
                "command": _truncate(row.get("Command"), 96),
                "created": _human_created(row.get("Created")),
                "status": _truncate(row.get("Status"), 80),
                "state": state,
                "ports": _truncate(_format_ports(row.get("Ports") or []), 120),
                "names": _truncate(", ".join(n.lstrip("/") for n in (row.get("Names") or [])), 120)
            })
        return {"running": running, "total": len(rows), "containers": containers, "limit": DOCKER_CONTAINER_LIMIT, "truncated": len(rows) > len(containers)}
    except Exception as e:
        return {"running": 0, "total": 0, "containers": [], "error": str(e)}

def get_hermes_profiles():
    profiles = []
    try:
        for path in sorted(glob.glob(os.path.join(HERMES_STATUS_DIR, "*.json"))):
            if os.path.basename(path) == "hardware.json":
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    item = json.load(f)
                if not isinstance(item, dict):
                    continue
                profile = str(item.get("profile") or os.path.splitext(os.path.basename(path))[0])
                usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
                profiles.append({
                    "profile": profile,
                    "agent_version": str(item.get("agent_version") or ""),
                    "api_status": str(item.get("api_status") or "unknown"),
                    "api_base_url": str(item.get("api_base_url") or ""),
                    "service_status": str(item.get("service_status") or item.get("status") or "unknown"),
                    "gateway_service": str(item.get("gateway_service") or item.get("service_status") or "unknown"),
                    "manager_mode": str(item.get("manager_mode") or ""),
                    "usage_mode": str(item.get("usage_mode") or ""),
                    "provider": str(item.get("provider") or ""),
                    "model": str(item.get("model") or "-"),
                    "auth_refreshed_at": str(item.get("auth_refreshed_at") or item.get("refreshed_at") or ""),
                    "scheduled_jobs_active": int(item.get("scheduled_jobs_active") or item.get("yesterday_success") or 0),
                    "scheduled_jobs_total": int(item.get("scheduled_jobs_total") or item.get("yesterday_total") or 0),
                    "sessions_active": int(item.get("sessions_active") or 0),
                    "sessions_total": int(item.get("sessions_total") or 0),
                    "sessions_has_more": bool(item.get("sessions_has_more")),
                    "running_agents": int(item.get("running_agents") or 0),
                    "resource_status": str(item.get("resource_status") or ""),
                    "usage": {
                        "input_tokens": int(usage.get("input_tokens") or 0),
                        "output_tokens": int(usage.get("output_tokens") or 0),
                        "total_tokens": int(usage.get("total_tokens") or item.get("yesterday_tokens") or item.get("tokens") or 0),
                        "estimated": bool(usage.get("estimated")),
                    },
                    "yesterday_success": int(item.get("yesterday_success") or 0),
                    "yesterday_total": int(item.get("yesterday_total") or 0),
                    "yesterday_tokens": int(item.get("yesterday_tokens") or item.get("tokens") or 0),
                    "last_run_at": str(item.get("last_run_at") or ""),
                    "note": str(item.get("note") or ""),
                    "mixture_of_agents": item.get("mixture_of_agents") if isinstance(item.get("mixture_of_agents"), dict) else {},
                    "config_summary": item.get("config_summary") if isinstance(item.get("config_summary"), dict) else {}
                })
            except Exception:
                continue
        return {"profiles": profiles}
    except Exception as e:
        return {"profiles": [], "error": str(e)}

def _ping_thread(host, mark, port):
    lostPacket = 0
    packet_queue = Queue(maxsize=PING_PACKET_HISTORY_LEN)

    while True:
        # flush dns, every time.
        IP = host
        if host.count(':') < 1:  # if not plain ipv6 address, means ipv4 address or hostname
            try:
                if PROBE_PROTOCOL_PREFER == 'ipv4':
                    IP = socket.getaddrinfo(host, None, socket.AF_INET)[0][4][0]
                else:
                    IP = socket.getaddrinfo(host, None, socket.AF_INET6)[0][4][0]
            except Exception:
                pass

        if packet_queue.full():
            if packet_queue.get() == 0:
                lostPacket -= 1
        try:
            b = timeit.default_timer()
            socket.create_connection((IP, port), timeout=1).close()
            pingTime[mark] = int((timeit.default_timer() - b) * 1000)
            packet_queue.put(1)
        except socket.error as error:
            if error.errno == errno.ECONNREFUSED:
                pingTime[mark] = int((timeit.default_timer() - b) * 1000)
                packet_queue.put(1)
            #elif error.errno == errno.ETIMEDOUT:
            else:
                lostPacket += 1
                packet_queue.put(0)

        if packet_queue.qsize() > 30:
            lostRate[mark] = float(lostPacket) / packet_queue.qsize()

        time.sleep(INTERVAL)

def _net_speed():
    while True:
        avgrx = 0
        avgtx = 0
        for name, stats in psutil.net_io_counters(pernic=True).items():
            if "lo" in name or "tun" in name \
                    or "docker" in name or "veth" in name \
                    or "br-" in name or "vmbr" in name \
                    or "vnet" in name or "kube" in name:
                continue
            avgrx += stats.bytes_recv
            avgtx += stats.bytes_sent
        now_clock = time.time()
        netSpeed["diff"] = now_clock - netSpeed["clock"]
        netSpeed["clock"] = now_clock
        netSpeed["netrx"] = int((avgrx - netSpeed["avgrx"]) / netSpeed["diff"])
        netSpeed["nettx"] = int((avgtx - netSpeed["avgtx"]) / netSpeed["diff"])
        netSpeed["avgrx"] = avgrx
        netSpeed["avgtx"] = avgtx
        time.sleep(INTERVAL)

def _disk_io():
    """
    the code is by: https://github.com/giampaolo/psutil/blob/master/scripts/iotop.py
    good luck for opensource! modify: cpp.la
    Calculate IO usage by comparing IO statics before and
        after the interval.
        Return a tuple including all currently running processes
        sorted by IO activity and total disks I/O activity.
    磁盘IO：因为IOPS原因，SSD和HDD、包括RAID卡，ZFS等。IO对性能的影响还需要结合自身服务器情况来判断。
    比如我这里是机械硬盘，大量做随机小文件读写，那么很低的读写也就能造成硬盘长时间的等待。
    如果这里做连续性IO，那么普通机械硬盘写入到100Mb/s，那么也能造成硬盘长时间的等待。
    磁盘读写有误差：4k，8k ，https://stackoverflow.com/questions/34413926/psutil-vs-dd-monitoring-disk-i-o
    macos/win，暂不处理。
    """
    if "darwin" in sys.platform or "win" in sys.platform:
        diskIO["read"] = 0
        diskIO["write"] = 0
    else:
        while True:
            # first get a list of all processes and disk io counters
            procs = [p for p in psutil.process_iter()]
            for p in procs[:]:
                try:
                    p._before = p.io_counters()
                except psutil.Error:
                    procs.remove(p)
                    continue
            disks_before = psutil.disk_io_counters()

            # sleep some time, only when INTERVAL==1 , io read/write per_sec.
            # when INTERVAL > 1, io read/write per_INTERVAL
            time.sleep(INTERVAL)

            # then retrieve the same info again
            for p in procs[:]:
                with p.oneshot():
                    try:
                        p._after = p.io_counters()
                        p._cmdline = ' '.join(p.cmdline())
                        if not p._cmdline:
                            p._cmdline = p.name()
                        p._username = p.username()
                    except (psutil.NoSuchProcess, psutil.ZombieProcess):
                        procs.remove(p)
            disks_after = psutil.disk_io_counters()

            # finally calculate results by comparing data before and
            # after the interval
            for p in procs:
                p._read_per_sec = p._after.read_bytes - p._before.read_bytes
                p._write_per_sec = p._after.write_bytes - p._before.write_bytes
                p._total = p._read_per_sec + p._write_per_sec

            diskIO["read"] = disks_after.read_bytes - disks_before.read_bytes
            diskIO["write"] = disks_after.write_bytes - disks_before.write_bytes

def get_realtime_data():
    '''
    real time get system data
    :return:
    '''
    t1 = threading.Thread(
        target=_ping_thread,
        kwargs={
            'host': CU,
            'mark': '10010',
            'port': PROBEPORT
        }
    )
    t2 = threading.Thread(
        target=_ping_thread,
        kwargs={
            'host': CT,
            'mark': '189',
            'port': PROBEPORT
        }
    )
    t3 = threading.Thread(
        target=_ping_thread,
        kwargs={
            'host': CM,
            'mark': '10086',
            'port': PROBEPORT
        }
    )
    t4 = threading.Thread(
        target=_net_speed,
    )
    t5 = threading.Thread(
        target=_disk_io,
    )
    for ti in [t1, t2, t3, t4, t5]:
        ti.daemon = True
        ti.start()

def _monitor_thread(name, host, interval, type):
    # 参考 _ping_thread 风格：每轮解析一次目标，按协议族偏好解析 IP，测 TCP 建连耗时
    while True:
        if name not in monitorServer:
            break
        try:
            # 1) 解析目标 host 与端口
            if type == 'http':
                addr = str(host).replace('http://','')
                addr = addr.split('/',1)[0]
                port = 80
                if ':' in addr and not addr.startswith('['):
                    a, p = addr.rsplit(':',1)
                    if p.isdigit():
                        addr, port = a, int(p)
            elif type == 'https':
                addr = str(host).replace('https://','')
                addr = addr.split('/',1)[0]
                port = 443
                if ':' in addr and not addr.startswith('['):
                    a, p = addr.rsplit(':',1)
                    if p.isdigit():
                        addr, port = a, int(p)
            elif type == 'tcp':
                addr = str(host)
                if addr.startswith('[') and ']' in addr:
                    # [v6]:port
                    a = addr[1:addr.index(']')]
                    rest = addr[addr.index(']')+1:]
                    if rest.startswith(':') and rest[1:].isdigit():
                        addr, port = a, int(rest[1:])
                    else:
                        raise Exception('bad tcp target')
                else:
                    a, p = addr.rsplit(':',1)
                    addr, port = a, int(p)
            else:
                time.sleep(interval)
                continue

            # 2) 解析 IP（按偏好族），与 _ping_thread 保持一致的判定
            IP = addr
            if addr.count(':') < 1:  # 非纯 IPv6，可能是 IPv4 或域名
                try:
                    if PROBE_PROTOCOL_PREFER == 'ipv4':
                        IP = socket.getaddrinfo(addr, None, socket.AF_INET)[0][4][0]
                    else:
                        IP = socket.getaddrinfo(addr, None, socket.AF_INET6)[0][4][0]
                except Exception:
                    pass

            # 3) 测 TCP 建连耗时（timeout=1s）；ECONNREFUSED 也记为耗时
            try:
                b = timeit.default_timer()
                socket.create_connection((IP, port), timeout=1).close()
                monitorServer[name]['latency'] = int((timeit.default_timer() - b) * 1000)
            except socket.error as error:
                if getattr(error, 'errno', None) == errno.ECONNREFUSED:
                    monitorServer[name]['latency'] = int((timeit.default_timer() - b) * 1000)
                else:
                    monitorServer[name]['latency'] = 0
        except Exception:
            monitorServer[name]['latency'] = 0
        time.sleep(interval)


def byte_str(object):
    '''
    bytes to str, str to bytes
    :param object:
    :return:
    '''
    if isinstance(object, str):
        return object.encode(encoding="utf-8")
    elif isinstance(object, bytes):
        return bytes.decode(object)
    else:
        print(type(object))

if __name__ == '__main__':
    for argc in sys.argv:
        if 'SERVER' in argc:
            SERVER = argc.split('SERVER=')[-1]
        elif 'PORT' in argc:
            PORT = int(argc.split('PORT=')[-1])
        elif 'USER' in argc:
            USER = argc.split('USER=')[-1]
        elif 'PASSWORD' in argc:
            PASSWORD = argc.split('PASSWORD=')[-1]
        elif 'INTERVAL' in argc:
            INTERVAL = int(argc.split('INTERVAL=')[-1])
    socket.setdefaulttimeout(30)
    get_realtime_data()
    while 1:
        try:
            print("Connecting...")
            s = socket.create_connection((SERVER, PORT))
            data = byte_str(s.recv(1024))
            if data.find("Authentication required") > -1:
                s.send(byte_str(USER + ':' + PASSWORD + '\n'))
                data = byte_str(s.recv(1024))
                if data.find("Authentication successful") < 0:
                    print(data)
                    raise socket.error
            else:
                print(data)
                raise socket.error

            print(data)
            if data.find("You are connecting via") < 0:
                data = byte_str(s.recv(1024))
                print(data)
                for i in data.split('\n'):
                    if "monitor" in i and "type" in i and "{" in i and "}" in i:
                        jdata = json.loads(i[i.find("{"):i.find("}")+1])
                        monitorServer[jdata.get("name")] = {
                            "type": jdata.get("type"),
                            "host": jdata.get("host"),
                            "latency": 0
                        }
                        t = threading.Thread(
                            target=_monitor_thread,
                            kwargs={
                                'name': jdata.get("name"),
                                'host': jdata.get("host"),
                                'interval': jdata.get("interval"),
                                'type': jdata.get("type")
                            }
                        )
                        t.daemon = True
                        t.start()

            timer = 0
            check_ip = 0
            if data.find("IPv4") > -1:
                check_ip = 6
            elif data.find("IPv6") > -1:
                check_ip = 4
            else:
                print(data)
                raise socket.error

            while 1:
                CPU = get_cpu()
                NET_IN, NET_OUT = liuliang()
                Uptime = get_uptime()
                Load_1, Load_5, Load_15 = os.getloadavg() if 'linux' in sys.platform or 'darwin' in sys.platform else (0.0, 0.0, 0.0)
                MemoryTotal, MemoryUsed = get_memory()
                SwapTotal, SwapUsed = get_swap()
                HDDTotal, HDDUsed = get_hdd()
                array = {}
                if not timer:
                    array['online' + str(check_ip)] = get_network(check_ip)
                    timer = 10
                else:
                    timer -= 1*INTERVAL

                array['uptime'] = Uptime
                array['load_1'] = Load_1
                array['load_5'] = Load_5
                array['load_15'] = Load_15
                array['memory_total'] = MemoryTotal
                array['memory_used'] = MemoryUsed
                array['swap_total'] = SwapTotal
                array['swap_used'] = SwapUsed
                array['hdd_total'] = HDDTotal
                array['hdd_used'] = HDDUsed
                array['cpu'] = CPU
                array['network_rx'] = netSpeed.get("netrx")
                array['network_tx'] = netSpeed.get("nettx")
                array['network_in'] = NET_IN
                array['network_out'] = NET_OUT
                array['ping_10010'] = lostRate.get('10010') * 100
                array['ping_189'] = lostRate.get('189') * 100
                array['ping_10086'] = lostRate.get('10086') * 100
                array['time_10010'] = pingTime.get('10010')
                array['time_189'] = pingTime.get('189')
                array['time_10086'] = pingTime.get('10086')
                array['tcp'], array['udp'], array['process'], array['thread'] = tupd()
                array['io_read'] = diskIO.get("read")
                array['io_write'] = diskIO.get("write")
                array['os'] = get_host_os_name()
                items = []
                for _n, st in monitorServer.items():
                    key = str(_n)
                    try:
                        ms = int(st.get('latency') or 0)
                    except Exception:
                        ms = 0
                    items.append((key, max(0, ms)))
                # 稳定顺序：按 key 排序
                items.sort(key=lambda x: x[0])
                array['custom'] = ';'.join(f"{k}={v}" for k,v in items)
                array['hardware_json'] = _json_compact(get_hardware_health())
                array['docker_json'] = _json_compact_limited(
                    get_docker_containers(),
                    DOCKER_JSON_MAX_BYTES,
                    "containers",
                    {"running": 0, "total": 0, "containers": []}
                )
                array['hermes_json'] = _json_compact_limited(
                    get_hermes_profiles(),
                    HERMES_JSON_MAX_BYTES,
                    "profiles",
                    {"profiles": []}
                )
                s.send(byte_str("update " + json.dumps(array) + "\n"))
        except KeyboardInterrupt:
            raise
        except socket.error:
            monitorServer.clear()
            print("Disconnected...")
            if 's' in locals().keys():
                del s
            time.sleep(3)
        except Exception as e:
            monitorServer.clear()
            print("Caught Exception:", e)
            if 's' in locals().keys():
                del s
            time.sleep(3)
