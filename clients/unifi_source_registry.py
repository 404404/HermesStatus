"""Fixed symbolic source registry; profiles never contain shell commands."""

KNOWN_SOURCES = frozenset({
    "unifi.cpu.temperature.ubnt_systool", "linux.proc.stat", "linux.proc.meminfo",
    "linux.proc.uptime", "linux.proc.loadavg", "unifi.cpu.cpuload",
    "linux.sys.thermal", "linux.sys.hwmon", "linux.sensors_json",
    "unifi.udw.ustd_hw_polling",
})
CORE_SOURCES = frozenset({
    "unifi.cpu.temperature.ubnt_systool", "linux.proc.stat", "linux.proc.meminfo",
    "linux.proc.uptime", "linux.proc.loadavg",
})

REMOTE_CORE_SCRIPT = r'''set -eu
printf '%s\n' '__HS_CPU_TEMP__'
/sbin/ubnt-systool cputemp
printf '%s\n' '__HS_PROC_STAT__'
awk '/^cpu / {print; exit}' /proc/stat
printf '%s\n' '__HS_MEMINFO__'
awk '/^(MemTotal|MemAvailable|MemFree|Buffers|Cached|SwapTotal|SwapFree):/ {print}' /proc/meminfo
printf '%s\n' '__HS_UPTIME__'
cat /proc/uptime
printf '%s\n' '__HS_LOADAVG__'
cat /proc/loadavg
printf '%s\n' '__HS_END__'
'''

REMOTE_DIAGNOSTICS_SCRIPT = r'''set -eu
printf '%s\n' '__HS_THERMAL__'
for z in /sys/class/thermal/thermal_zone[0-9]*; do
  [ -d "$z" ] || continue
  n=${z##*/thermal_zone}
  printf 'zone=%s type=%s temp=%s\n' "$n" "$(cat "$z/type" 2>/dev/null || printf unknown)" "$(cat "$z/temp" 2>/dev/null || printf unknown)"
done
printf '%s\n' '__HS_HWMON__'
/usr/bin/sensors -j 2>/dev/null || true
printf '%s\n' '__HS_HW_CACHE__'
if [ -f /var/run/ustd/hw_polling.cache ] && [ -r /var/run/ustd/hw_polling.cache ]; then
  head -c 12000 /var/run/ustd/hw_polling.cache
  printf "\n"
fi
printf '%s\n' '__HS_END__'
'''
