#!/usr/bin/env python3
# coding: utf-8
# Update by : https://github.com/cppla/ServerStatus, Update date: 20250902
# 依赖于psutil跨平台库
# 版本：1.1.0, 支持Python版本：3.6+
# 支持操作系统： Linux, Windows, OSX, Sun Solaris, FreeBSD, OpenBSD and NetBSD, both 32-bit and 64-bit architectures
# 说明: 默认情况下修改 SERVER 和 USER 即可。

SERVER = ""
USER = ""


PASSWORD = "USER_DEFAULT_PASSWORD"
PORT = 35601
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

from host_collector import HostExtensionCollector, add_extension_payload, collect_client_build
from device_client_config import ClientMode, load_client_selection
from device_client_transport import (
    create_device_v2_runner,
    install_monitor_definitions,
)
from multi_device_contracts import ClientContractError

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

# Allow docker env overrides. 优先级：运行程序传递参数 > 用户修改的USER > Docker/系统
SERVER = _env_str("SERVER", SERVER) if SERVER == "" else SERVER
USER = _env_str("SERVERSTATUS_USER", _env_str("USER", USER)) if USER == "" else USER
PASSWORD = _env_str("PASSWORD", PASSWORD)
PORT = _env_int("PORT", PORT)
INTERVAL = _env_int("INTERVAL", INTERVAL)

def parse_cli_args(arguments):
    overrides = {}
    for argument in arguments:
        key, separator, value = argument.partition('=')
        if separator and key in {'SERVER', 'PORT', 'USER', 'PASSWORD', 'INTERVAL'}:
            overrides[key] = value
    return overrides

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

def get_cpu_cores():
    return psutil.cpu_count(logical=True) or 0

def normalize_cpu_model(value):
    return " ".join(str(value or "").split())[:160]

def is_generic_cpu_model(value):
    v = normalize_cpu_model(value).lower().replace('-', '').replace('_', '').replace(' ', '')
    return v in ('', 'unknown', 'x8664', 'amd64', 'i386', 'i686', 'aarch64', 'arm64') or v.startswith('armv')

def get_platform_cpu_vendor():
    values = [
        platform.processor(),
        getattr(platform.uname(), 'processor', ''),
        platform.machine(),
        getattr(platform.uname(), 'machine', ''),
        platform.platform(),
    ]
    text = " ".join(normalize_cpu_model(v).lower() for v in values)
    if 'genuineintel' in text:
        return 'GenuineIntel'
    if 'authenticamd' in text:
        return 'AuthenticAMD'
    if 'intel' in text:
        return 'Intel'
    if 'amd' in text:
        return 'AMD'
    if sys.platform.startswith('darwin') and platform.machine().lower() in ('arm64', 'aarch64'):
        return 'Apple'
    if any(token in text for token in ('aarch64', 'arm64', 'armv7', 'armv8', ' arm ')):
        return 'ARM'
    return ''

def get_platform_cpu_arch():
    return normalize_cpu_model(platform.machine() or platform.processor() or platform.architecture()[0])

def get_cpu_model():
    for value in (platform.processor(), getattr(platform.uname(), 'processor', '')):
        value = normalize_cpu_model(value)
        if value and not is_generic_cpu_model(value):
            return value
    vendor = normalize_cpu_model(get_platform_cpu_vendor())
    if vendor:
        return vendor
    return get_platform_cpu_arch()

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
monitorServerLock = threading.RLock()

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
    """Start local throughput and disk-I/O sampling threads."""
    for target in (_net_speed, _disk_io):
        thread = threading.Thread(target=target)
        thread.daemon = True
        thread.start()

def _monitor_thread(name, host, interval, type, generation=None):
    # Each configured custom monitor measures its own TCP connection latency.
    while True:
        if not _monitor_owned(name, generation):
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

            # 2) Use the platform resolver for the configured monitor target.
            IP = addr

            # 3) 测 TCP 建连耗时（timeout=1s）；ECONNREFUSED 也记为耗时
            try:
                b = timeit.default_timer()
                socket.create_connection((IP, port), timeout=1).close()
                _set_monitor_latency(
                    name,
                    int((timeit.default_timer() - b) * 1000),
                    generation,
                )
            except socket.error as error:
                if getattr(error, 'errno', None) == errno.ECONNREFUSED:
                    _set_monitor_latency(
                        name,
                        int((timeit.default_timer() - b) * 1000),
                        generation,
                    )
                else:
                    _set_monitor_latency(name, 0, generation)
        except Exception:
            _set_monitor_latency(name, 0, generation)
        time.sleep(interval)


def _monitor_owned(name, generation):
    with monitorServerLock:
        monitor = monitorServer.get(name)
        return monitor is not None and (
            generation is None or monitor.get("_generation") == generation
        )


def _set_monitor_latency(name, latency, generation):
    with monitorServerLock:
        monitor = monitorServer.get(name)
        if monitor is not None and (
            generation is None or monitor.get("_generation") == generation
        ):
            monitor["latency"] = latency


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


def _device_v2_stats_collector(extension_collector):
    cpu_cores = get_cpu_cores()

    def collect():
        cpu = get_cpu()
        net_in, net_out = liuliang()
        uptime = get_uptime()
        load_1, load_5, load_15 = (
            os.getloadavg()
            if 'linux' in sys.platform or 'darwin' in sys.platform
            else (0.0, 0.0, 0.0)
        )
        memory_total, memory_used = get_memory()
        swap_total, swap_used = get_swap()
        hdd_total, hdd_used = get_hdd()
        hdd_total, hdd_used = extension_collector.preferred_disk_usage(hdd_total, hdd_used)
        stats = {
            'uptime': uptime,
            'load_1': load_1,
            'load_5': load_5,
            'load_15': load_15,
            'memory_total': memory_total,
            'memory_used': memory_used,
            'swap_total': swap_total,
            'swap_used': swap_used,
            'hdd_total': hdd_total,
            'hdd_used': hdd_used,
            'cpu': cpu,
            'cpu_cores': cpu_cores,
            'cpu_model': extension_collector.cpu_model or "",
            'network_rx': netSpeed.get("netrx"),
            'network_tx': netSpeed.get("nettx"),
            'network_in': net_in,
            'network_out': net_out,
            'io_read': diskIO.get("read"),
            'io_write': diskIO.get("write"),
            'os': extension_collector.host_os,
        }
        stats['tcp'], stats['udp'], stats['process'], stats['thread'] = tupd()
        with monitorServerLock:
            monitor_snapshot = list(monitorServer.items())
        items = []
        for name, monitor in monitor_snapshot:
            try:
                latency = int(monitor.get('latency') or 0)
            except Exception:
                latency = 0
            items.append((str(name), max(0, latency)))
        items.sort(key=lambda item: item[0])
        stats['custom'] = ';'.join(f"{key}={value}" for key, value in items)
        add_extension_payload(stats, extension_collector)
        return stats

    return collect


def _run_device_v2(config, extension_collector):
    def apply_monitors(monitors):
        with monitorServerLock:
            install_monitor_definitions(
                monitorServer,
                monitors,
                thread_target=_monitor_thread,
            )

    runner = create_device_v2_runner(
        config,
        collect_stats=_device_v2_stats_collector(extension_collector),
        apply_monitors=apply_monitors,
    )
    extension_collector.start()
    get_realtime_data()
    runner.run_forever()


def _device_v2_extension_collector(config, arguments):
    smart_devices = None
    if config.smart_devices is not None:
        smart_devices = [
            {"path": device.path, "type": device.type, "label": device.label}
            for device in config.smart_devices
        ]
    filesystem_probes = [
        {"mountpoint": probe.mountpoint, "probe_path": probe.probe_path}
        for probe in config.filesystem_probes
    ]
    return HostExtensionCollector(
        smart_devices=smart_devices,
        primary_smart_device=config.primary_smart_device,
        filesystem_probes=filesystem_probes,
        client_build=collect_client_build(protocol="device_v2"),
        easytier_args=arguments,
    )


if __name__ == '__main__':
    try:
        client_selection = load_client_selection(sys.argv[1:])
    except ClientContractError:
        print("Client configuration error: invalid_device_v2_configuration", file=sys.stderr)
        sys.exit(2)
    if client_selection.mode is ClientMode.DEVICE_V2:
        try:
            _run_device_v2(
                client_selection.device_v2,
                _device_v2_extension_collector(client_selection.device_v2, sys.argv[1:]),
            )
        except ClientContractError:
            print("Client configuration error: invalid_device_v2_configuration", file=sys.stderr)
            sys.exit(2)
        sys.exit(0)

    cli_args = parse_cli_args(sys.argv[1:])
    SERVER = cli_args.get('SERVER', SERVER)
    PORT = int(cli_args.get('PORT', PORT))
    USER = cli_args.get('USER', USER)
    PASSWORD = cli_args.get('PASSWORD', PASSWORD)
    INTERVAL = int(cli_args.get('INTERVAL', INTERVAL))
    socket.setdefaulttimeout(30)
    extension_collector = HostExtensionCollector(
        easytier_args=sys.argv[1:], collect_build_metadata=False
    )
    extension_collector.start()
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

            CPUCores = get_cpu_cores()
            CPUModel = extension_collector.cpu_model or ""
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
                array['cpu_cores'] = CPUCores
                array['cpu_model'] = CPUModel
                array['network_rx'] = netSpeed.get("netrx")
                array['network_tx'] = netSpeed.get("nettx")
                array['network_in'] = NET_IN
                array['network_out'] = NET_OUT
                array['tcp'], array['udp'], array['process'], array['thread'] = tupd()
                array['io_read'] = diskIO.get("read")
                array['io_write'] = diskIO.get("write")
                array['os'] = extension_collector.host_os
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
                add_extension_payload(array, extension_collector)
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
