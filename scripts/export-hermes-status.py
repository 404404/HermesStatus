#!/usr/bin/env python3
import datetime as dt
import glob
import http.client
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from hermes_config_summary import summarize_config


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _string(value):
    return "" if value is None else str(value)


def load_export_config():
    path = os.environ.get("HERMES_EXPORT_CONFIG", "/app/hermes-exporter.json")
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.is_file():
        return {}
    text = config_path.read_text(encoding="utf-8", errors="replace")
    if config_path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def env_or_config(env_key, config, config_key, default=""):
    value = _dict(config.get("defaults")).get(config_key)
    if value is not None and str(value).strip() != "":
        return value
    value = config.get(config_key)
    if value is not None and str(value).strip() != "":
        return value
    return os.environ.get(env_key, default)


def normalize_profiles(config, hermes_root):
    raw = config.get("profiles")
    profiles = []
    if isinstance(raw, dict):
        raw = [{"name": name, **_dict(value)} for name, value in raw.items()]
    for item in _list(raw):
        if isinstance(item, str):
            item = {"name": item}
        item = _dict(item)
        name = _string(item.get("name") or item.get("profile")).strip()
        if not name:
            continue
        profile_dir = _string(item.get("profile_dir") or item.get("dir")).strip()
        if not profile_dir:
            profile_dir = str(Path(hermes_root) / name)
        config_path = _string(item.get("config_path") or item.get("hermes_config_path")).strip()
        if not config_path:
            config_path = str(Path(hermes_root) / ".hermes" / "profiles" / name / "config.yaml")
        normalized = dict(item)
        normalized.update({
            "name": name,
            "profile_dir": profile_dir,
            "config_path": config_path,
        })
        profiles.append(normalized)
    if profiles:
        return profiles
    names = [p.strip() for p in os.environ.get("HERMES_PROFILES", "hermes1,hermes2,hermes3").split(",") if p.strip()]
    return [
        {
            "name": name,
            "profile_dir": str(Path(hermes_root) / name),
            "config_path": str(Path(hermes_root) / ".hermes" / "profiles" / name / "config.yaml"),
        }
        for name in names
    ]


EXPORT_CONFIG = load_export_config()
CONFIG_HAS_PROFILES = bool(EXPORT_CONFIG.get("profiles"))
HERMES_ROOT = Path(env_or_config("HERMES_ROOT", EXPORT_CONFIG, "hermes_root", "/home/hermes"))
OUTPUT_DIR = Path(env_or_config("HERMES_STATUS_DIR", EXPORT_CONFIG, "status_dir", "/home/hermes/server-status/hermes-status"))
PROFILE_CONFIGS = normalize_profiles(EXPORT_CONFIG, HERMES_ROOT)
PROFILE_BY_NAME = {item["name"]: item for item in PROFILE_CONFIGS}
PROFILES = [item["name"] for item in PROFILE_CONFIGS]
DEFAULT_PORTS = {
    item["name"]: int(item.get("api_port") or _dict(item.get("api")).get("port") or 0)
    for item in PROFILE_CONFIGS
    if str(item.get("api_port") or _dict(item.get("api")).get("port") or "").strip()
}
for _profile, _port in {"hermes1": 8642, "hermes2": 8643, "hermes3": 8644}.items():
    if _profile in PROFILES and _profile not in DEFAULT_PORTS:
        DEFAULT_PORTS[_profile] = _port
API_TIMEOUT = float(os.environ.get("HERMES_API_TIMEOUT", "2.5"))
MAX_TABLE_ROWS = int(os.environ.get("HERMES_EXPORT_TABLE_LIMIT", "20"))
API_PAGE_LIMIT = int(os.environ.get("HERMES_API_PAGE_LIMIT", "100"))
API_MAX_PAGES = int(os.environ.get("HERMES_API_MAX_PAGES", "100"))
HOST_USER = os.environ.get("HERMES_HOST_USER", "hermes")
PROFILE_ENV_CACHE = {}
HERMES_VERSION_CACHE = None
TRUE_VALUES = {"1", "true", "yes", "on"}


def profile_config(profile):
    return PROFILE_BY_NAME.get(profile, {})


def profile_dir_for(profile):
    if not CONFIG_HAS_PROFILES:
        return HERMES_ROOT / profile
    return Path(profile_config(profile).get("profile_dir") or (HERMES_ROOT / profile))


def profile_config_path_for(profile):
    if not CONFIG_HAS_PROFILES:
        return str(HERMES_ROOT / ".hermes" / "profiles" / profile / "config.yaml")
    return _string(profile_config(profile).get("config_path")).strip()


def run_text(cmd):
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=8)
        return proc.stdout.strip()
    except Exception:
        return ""


def run_host_text(command):
    if not run_text(["sh", "-lc", "command -v nsenter"]):
        return ""
    quoted = command.replace("'", "'\"'\"'")
    user = HOST_USER.replace("'", "'\"'\"'")
    return run_text([
        "nsenter",
        "-t",
        "1",
        "-m",
        "-u",
        "-i",
        "-n",
        "-p",
        "--",
        "su",
        "-",
        user,
        "-c",
        quoted,
    ])


def run_json(cmd):
    text = run_text(cmd)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def env_name(prefix, profile):
    return "%s_%s" % (prefix, re.sub(r"[^A-Za-z0-9]+", "_", profile).upper())


def load_profile_env(profile):
    if profile in PROFILE_ENV_CACHE:
        return PROFILE_ENV_CACHE[profile]
    data = {}
    pconf = profile_config(profile)
    path = Path(pconf.get("env_path") or (profile_dir_for(profile) / ".env"))
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        pass
    PROFILE_ENV_CACHE[profile] = data
    return data


def api_base_url(profile):
    pconf = profile_config(profile)
    api_config = _dict(pconf.get("api"))
    profile_env = load_profile_env(profile)
    enabled_values = [
        api_config.get("enabled"),
        pconf.get("api_enabled"),
        os.environ.get(env_name("HERMES_API_ENABLED", profile)),
        os.environ.get(env_name("API_SERVER_ENABLED", profile)),
        os.environ.get("HERMES_API_ENABLED"),
        os.environ.get("API_SERVER_ENABLED"),
        profile_env.get("API_SERVER_ENABLED"),
    ]
    configured_enabled = [value for value in enabled_values if value is not None and str(value).strip() != ""]
    enabled = any(str(value or "").strip().lower() in TRUE_VALUES for value in configured_enabled)
    # Existing profiles on the target expose API_SERVER_KEY/API_SERVER_PORT
    # without API_SERVER_ENABLED. Treat that as an explicit local API config,
    # but still require a bearer token before making API requests.
    if not enabled and configured_enabled:
        return ""
    if not enabled and not api_token(profile):
        return ""
    configured_base_url = _string(api_config.get("base_url") or pconf.get("api_base_url")).strip()
    if configured_base_url:
        return configured_base_url.rstrip("/")
    value = os.environ.get(env_name("HERMES_API_BASE_URL", profile))
    if value:
        return value.rstrip("/")
    env_port = _string(api_config.get("port") or pconf.get("api_port") or profile_env.get("API_SERVER_PORT")).strip()
    env_host = _string(api_config.get("host") or pconf.get("api_host") or profile_env.get("API_SERVER_HOST") or "127.0.0.1").strip()
    if env_host in ("0.0.0.0", "::"):
        env_host = "127.0.0.1"
    if env_port:
        return "http://%s:%s" % (env_host, env_port)
    port = DEFAULT_PORTS.get(profile)
    if not port:
        return ""
    return "http://127.0.0.1:%d" % port


def api_token(profile):
    pconf = profile_config(profile)
    api_config = _dict(pconf.get("api"))
    profile_env = load_profile_env(profile)
    keys = [
        env_name("HERMES_API_TOKEN", profile),
        env_name("API_SERVER_KEY", profile),
        "%s_API_SERVER_KEY" % profile.upper(),
        "API_SERVER_KEY",
        "HERMES_API_TOKEN",
    ]
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return _string(api_config.get("token") or pconf.get("api_token") or api_config.get("api_server_key") or pconf.get("api_server_key") or profile_env.get("API_SERVER_KEY") or profile_env.get("HERMES_API_TOKEN"))


def http_json(profile, path, method="GET", payload=None):
    base = api_base_url(profile)
    if not base:
        return None, "missing base_url"
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https"):
        return None, "unsupported scheme"
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    body = None
    headers = {"Accept": "application/json"}
    token = api_token(profile)
    if not token:
        return None, "missing API_SERVER_KEY"
    headers["Authorization"] = "Bearer %s" % token
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    url_path = (parsed.path.rstrip("/") + path) if parsed.path else path
    try:
        conn = conn_cls(parsed.hostname, parsed.port, timeout=API_TIMEOUT)
        conn.request(method, url_path, body=body, headers=headers)
        res = conn.getresponse()
        raw = res.read(300000)
        conn.close()
        if res.status < 200 or res.status >= 300:
            return None, "HTTP %d" % res.status
        if not raw:
            return {}, ""
        return json.loads(raw.decode("utf-8", errors="replace")), ""
    except Exception as exc:
        return None, str(exc)


def service_status(profile):
    candidates = [
        f"hermes-gateway-{profile}.service",
        f"hermes-agent-{profile}.service",
        f"hermes-{profile}.service",
        f"{profile}.service",
    ]
    for unit in candidates:
        state = run_text(["systemctl", "--user", "is-active", unit])
        if state:
            return state, unit
    return "unknown", ""


def hermes_cli_status(profile):
    candidates = [
        ["hermes", "-p", profile, "status"],
        ["hermes", "--profile", profile, "status"],
    ]
    for cmd in candidates:
        text = run_text(cmd)
        if text:
            return text
    safe_profile = re.sub(r"[^A-Za-z0-9_.:-]", "", profile)
    if safe_profile:
        text = run_host_text("hermes -p %s status" % safe_profile)
        if text:
            return text
    return ""


def hermes_agent_version():
    global HERMES_VERSION_CACHE
    if HERMES_VERSION_CACHE is not None:
        return HERMES_VERSION_CACHE

    outputs = []
    for cmd in (["hermes", "--version"], ["hermes", "version"]):
        value = run_text(cmd)
        if value:
            outputs.append(value)
            break
    if not outputs:
        value = run_host_text("hermes --version")
        if value:
            outputs.append(value)

    value = outputs[0] if outputs else ""
    value = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", value)
    value = " ".join(line.strip() for line in value.splitlines() if line.strip())
    version = re.search(r"\bv?\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?\b", value)
    HERMES_VERSION_CACHE = (version.group(0).lstrip("v") if version else value)[:120]
    return HERMES_VERSION_CACHE


def parse_cli_status(text):
    result = {}
    if not text:
        return result
    result["raw_status"] = "\n".join(text.splitlines()[:80])

    sections = {}
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("◆"):
            section = line.lstrip("◆").strip().lower()
            sections[section] = []
            continue
        if section:
            sections.setdefault(section, []).append(line)

    def clean_status(value):
        value = str(value or "").strip()
        value = value.replace("✓", "").replace("✗", "").strip()
        value = re.sub(r"\s+", " ", value)
        return value

    for line in sections.get("environment", []):
        if line.lower().startswith("model:"):
            result["model"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("provider:"):
            result["provider"] = line.split(":", 1)[1].strip()

    for line in sections.get("gateway service", []):
        if line.lower().startswith("status:"):
            result["gateway_service"] = clean_status(line.split(":", 1)[1])
        elif line.lower().startswith("manager:"):
            result["manager_mode"] = clean_status(line.split(":", 1)[1])

    jobs_text = " ".join(sections.get("scheduled jobs", []))
    jobs = re.search(r"jobs:\s*(\d+)\s*active\s*,\s*(\d+)\s*total", jobs_text, re.I)
    if jobs:
        result["scheduled_jobs_active"] = int(jobs.group(1))
        result["scheduled_jobs_total"] = int(jobs.group(2))
    else:
        jobs_single = re.search(r"jobs:\s*(\d+)", jobs_text, re.I)
        if jobs_single:
            total = int(jobs_single.group(1))
            result["scheduled_jobs_active"] = total
            result["scheduled_jobs_total"] = total

    sessions_text = " ".join(sections.get("sessions", []))
    sessions = re.search(r"active:\s*(\d+)", sessions_text, re.I)
    if sessions:
        result["active_sessions"] = int(sessions.group(1))
        result["sessions_total"] = int(sessions.group(1))

    api_key_providers = []
    for line in sections.get("api keys", []):
        if "✓" not in line:
            continue
        provider_name = line.split("✓", 1)[0].strip()
        if provider_name:
            api_key_providers.append(provider_name)

    auth_providers = []
    current_auth = None
    for line in sections.get("auth providers", []):
        if "✓" in line and "logged in" in line.lower():
            name = line.split("✓", 1)[0].strip()
            current_auth = {"name": name, "refreshed": ""}
            auth_providers.append(current_auth)
            continue
        if line.lower().startswith("refreshed:") and current_auth is not None:
            current_auth["refreshed"] = line.split(":", 1)[1].strip()

    result["api_key_providers"] = api_key_providers
    result["auth_providers"] = auth_providers
    if auth_providers:
        result["auth_refreshed_at"] = auth_providers[0].get("refreshed", "")

    provider_l = result.get("provider", "").lower()
    api_aliases = {
        "google ai studio": ("google", "gemini"),
        "openai": ("openai",),
        "openrouter": ("openrouter",),
        "deepseek": ("deepseek",),
        "xai": ("xai", "grok"),
        "nvidia": ("nvidia", "nim"),
        "kimi": ("kimi", "moonshot"),
        "z.ai": ("z.ai", "glm"),
        "minimax": ("minimax",),
        "anthropic": ("anthropic",),
    }
    auth_names = [item.get("name", "").lower() for item in auth_providers]
    api_names = [item.lower() for item in api_key_providers]
    if provider_l and any(provider_l == name or provider_l in name or name in provider_l for name in auth_names):
        result["usage_mode"] = "auth provider"
    elif any(any(alias in name or alias in provider_l for alias in api_aliases.get(provider_l, (provider_l,)) if alias) for name in api_names):
        result["usage_mode"] = "api"
    elif api_key_providers and not auth_providers:
        result["usage_mode"] = "api"
    elif auth_providers:
        result["usage_mode"] = "auth provider"

    if not result.get("gateway_service"):
        match = re.search(r"gateway\s+service\s*[:：]\s*([^\n]+)", text, re.I)
        if match:
            result["gateway_service"] = clean_status(match.group(1))
    return result


def iter_text_files(profile_dir):
    names = ["config.yaml", "config.yml", "config.json", ".env", "env.example"]
    for name in names:
        path = profile_dir / name
        if path.exists():
            yield path
    for path in sorted((profile_dir / "logs").glob("**/*.json"))[-80:]:
        yield path


def find_model(profile_dir):
    patterns = [
        re.compile(r'^\s*(?:model|MODEL)\s*[:=]\s*["\']?([^"\'#\n]+)', re.I),
        re.compile(r'"model"\s*:\s*"([^"]+)"', re.I),
    ]
    found = []
    for path in iter_text_files(profile_dir):
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                for pattern in patterns:
                    match = pattern.search(line)
                    if match:
                        value = match.group(1).strip().strip(",")
                        if value and value not in ("''", '""'):
                            found.append(value)
        except Exception:
            continue
    return found[-1] if found else "-"


def smart_candidates():
    configured = os.environ.get("SMART_DEVICE", "auto")
    if configured and configured != "auto":
        parts = configured.split()
        if "-d" in parts:
            index = parts.index("-d")
            dev = parts[-1]
            typ = parts[index + 1] if index + 1 < len(parts) else ""
            return [(dev, typ)]
        return [(configured, "")]
    devices = []
    scan = run_text(["smartctl", "--scan"])
    for line in scan.splitlines():
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
    for pattern in ("/dev/nvme*n1", "/dev/sd?", "/dev/vd?"):
        for dev in glob.glob(pattern):
            if (dev, "") not in devices:
                devices.append((dev, ""))
    return devices


def run_smartctl():
    for dev, typ in smart_candidates():
        type_variants = [""]
        if typ:
            type_variants.append(typ)
        for use_type in type_variants:
            typed_args = ["-d", use_type] if use_type else []
            data = {}
            source = ""
            text = ""
            text_source = ""
            text_commands = [
                ["sudo", "-n", "smartctl", "-x"] + typed_args + [dev],
                ["smartctl", "-x"] + typed_args + [dev],
                ["sudo", "-n", "smartctl", "-a"] + typed_args + [dev],
                ["smartctl", "-a"] + typed_args + [dev],
            ]
            for cmd in text_commands:
                out = run_text(cmd)
                if "START OF READ SMART DATA SECTION" in out or "SMART overall-health" in out:
                    text = out
                    text_source = " ".join(cmd)
                    break
            commands = [
                ["sudo", "-n", "smartctl", "-x", "-j"] + typed_args + [dev],
                ["smartctl", "-x", "-j"] + typed_args + [dev],
                ["sudo", "-n", "smartctl", "-a", "-j"] + typed_args + [dev],
                ["smartctl", "-a", "-j"] + typed_args + [dev],
            ]
            for cmd in commands:
                parsed = run_json(cmd)
                if isinstance(parsed, dict):
                    data = parsed
                    source = " ".join(cmd)
                    break
            if data or text:
                data["_device"] = dev
                data["_device_type"] = use_type
                data["_source"] = source or text_source
                data["_smart_text"] = text
                data["_smart_text_source"] = text_source
                return data
    return {}


def smart_attribute_raw(text, attr_id, attr_name):
    pattern = re.compile(r"^\s*%d\s+%s\b.*?\s-\s+(-?\d+)" % (attr_id, re.escape(attr_name)), re.I | re.M)
    match = pattern.search(text or "")
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None


def smart_stat_value(text, page, offset, description):
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


def smart_temperature_stats(data):
    text = data.get("_smart_text", "")
    current = smart_stat_value(text, "0x05", "0x008", "Current Temperature")
    highest = smart_stat_value(text, "0x05", "0x020", "Highest Temperature")
    lowest = smart_stat_value(text, "0x05", "0x028", "Lowest Temperature")
    if current is None:
        current = smart_temperature(data)
    return {
        "current": current,
        "highest": highest,
        "lowest": lowest,
    }


def smart_text_passed(text):
    match = re.search(r"SMART overall-health self-assessment test result:\s*([A-Z]+)", text or "", re.I)
    if not match:
        return None
    return match.group(1).lower() == "passed"


def first_number(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def nested_number(data, key_names):
    if isinstance(data, dict):
        for key, value in data.items():
            key_l = str(key).lower()
            if key_l in key_names:
                number = first_number(value)
                if number is not None:
                    return number
            found = nested_number(value, key_names)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = nested_number(item, key_names)
            if found is not None:
                return found
    return None


def smart_passed(data):
    text_passed = smart_text_passed(data.get("_smart_text", ""))
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
    grown = nested_number(data, {"scsi_grown_defect_list"})
    if grown is not None:
        return grown == 0
    return None


def smart_temperature(data):
    temp_194 = smart_attribute_raw(data.get("_smart_text", ""), 194, "Temperature_Celsius")
    if temp_194 is not None:
        return temp_194
    temp = (data.get("temperature") or {}).get("current")
    if temp is not None:
        return first_number(temp)
    return nested_number(data, {
        "current_temperature",
        "temperature_celsius",
        "drive_temperature",
        "temperature_current",
    })


def smart_power_on_hours(data):
    stat_hours = smart_stat_value(data.get("_smart_text", ""), "0x01", "0x010", "Power-on Hours")
    if stat_hours is not None:
        return int(stat_hours)
    text_hours = smart_attribute_raw(data.get("_smart_text", ""), 9, "Power_On_Hours")
    if text_hours is not None:
        return int(text_hours)
    hours = (data.get("power_on_time") or {}).get("hours")
    if hours is not None:
        return int(first_number(hours))
    found = nested_number(data, {
        "power_on_hours",
        "power_on_time_hours",
        "accumulated_power_on_hours",
    })
    return int(found) if found is not None else None


def smart_written_bytes(data):
    stat_lbas = smart_stat_value(data.get("_smart_text", ""), "0x01", "0x018", "Logical Sectors Written")
    if stat_lbas is not None:
        return int(stat_lbas) * 512
    text_lbas = smart_attribute_raw(data.get("_smart_text", ""), 241, "Total_LBAs_Written")
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
            number = first_number(write.get(key))
            if number is not None:
                return int(number * multiplier)
    return None


def smart_read_bytes(data):
    stat_lbas = smart_stat_value(data.get("_smart_text", ""), "0x01", "0x028", "Logical Sectors Read")
    if stat_lbas is not None:
        return int(stat_lbas) * 512
    return None


def export_hardware():
    smart = run_smartctl()
    passed = smart_passed(smart)
    temps = smart_temperature_stats(smart)
    temp = temps.get("current")
    payload = {
        "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "disk_temperature": {
            "value": float(temp),
            "current": float(temp),
            "highest": float(temps["highest"]) if temps.get("highest") is not None else None,
            "lowest": float(temps["lowest"]) if temps.get("lowest") is not None else None,
            "unit": "C",
            "source": "%s Device Statistics Temperature" % (smart.get("_device") or "smartctl"),
        } if temp is not None else None,
        "disk_smart_status": "passed" if passed is True else ("failed" if passed is False else "unknown"),
        "disk_power_on_hours": smart_power_on_hours(smart),
        "disk_written_bytes": smart_written_bytes(smart),
        "disk_read_bytes": smart_read_bytes(smart),
        "disk_device": smart.get("_device"),
        "disk_smart_source": smart.get("_smart_text_source") or smart.get("_source"),
    }
    atomic_write(OUTPUT_DIR / "hardware.json", payload)


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def json_times(data):
    keys = ("created_at", "started_at", "finished_at", "completed_at", "timestamp", "time", "date")
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, str):
                try:
                    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
                except Exception:
                    pass
    return None


def is_success(data):
    if not isinstance(data, dict):
        return False
    for key in ("success", "ok", "succeeded"):
        if key in data:
            return bool(data.get(key))
    status = str(data.get("status") or data.get("state") or data.get("result") or "").lower()
    if status:
        return status in ("success", "succeeded", "ok", "done", "completed", "complete")
    return not any(k in data for k in ("error", "exception", "failed"))


def token_sum(value):
    total = 0
    if isinstance(value, dict):
        for key, item in value.items():
            if "token" in str(key).lower() and isinstance(item, (int, float)):
                total += int(item)
            else:
                total += token_sum(item)
    elif isinstance(value, list):
        for item in value:
            total += token_sum(item)
    return total


def usage_from(value):
    if not isinstance(value, dict):
        return {}
    usage = value.get("usage") if isinstance(value.get("usage"), dict) else value
    if not any(key in usage for key in (
        "prompt_tokens",
        "input_tokens",
        "completion_tokens",
        "output_tokens",
        "total_tokens",
    )):
        return {}
    prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
    completion = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
    total = usage.get("total_tokens", 0) or prompt + completion
    return {"input_tokens": int(prompt), "output_tokens": int(completion), "total_tokens": int(total)}


def usage_add(left, right):
    if not right:
        return left
    out = dict(left or {})
    out["input_tokens"] = int(out.get("input_tokens") or 0) + int(right.get("input_tokens") or 0)
    out["output_tokens"] = int(out.get("output_tokens") or 0) + int(right.get("output_tokens") or 0)
    out["total_tokens"] = int(out.get("total_tokens") or 0) + int(right.get("total_tokens") or 0)
    return out


def usage_sum(value):
    total = {}
    if isinstance(value, dict):
        item = usage_from(value)
        if item:
            total = usage_add(total, item)
        for key, child in value.items():
            if key == "usage":
                continue
            total = usage_add(total, usage_sum(child))
    elif isinstance(value, list):
        for child in value:
            total = usage_add(total, usage_sum(child))
    return total


def list_items(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("data", "items", "sessions", "jobs", "runs", "models", "skills", "toolsets"):
            if isinstance(value.get(key), list):
                return value.get(key)
    return []


def mixture_of_agents_from_toolsets(value):
    items = list_items(value)
    for item in items:
        if not isinstance(item, dict):
            continue
        tools = [str(tool) for tool in _list(item.get("tools"))]
        name = first_string(item, ("name", "id", "key"))
        label = first_string(item, ("label", "title", "display_name"))
        haystack = " ".join([name, label, first_string(item, ("description",))] + tools).lower()
        if name.lower() != "moa" and "mixture_of_agents" not in tools and "mixture of agents" not in haystack:
            continue
        return {
            "source": "GET /v1/toolsets",
            "available": True,
            "name": name or "moa",
            "label": label or "Mixture of Agents",
            "description": first_string(item, ("description",)),
            "enabled": item.get("enabled") if isinstance(item.get("enabled"), bool) else None,
            "configured": item.get("configured") if isinstance(item.get("configured"), bool) else None,
            "tools": tools,
        }
    return {
        "source": "GET /v1/toolsets",
        "available": False,
        "name": "moa",
        "label": "Mixture of Agents",
        "description": "",
        "enabled": None,
        "configured": None,
        "tools": [],
    }


def first_string(value, keys):
    if not isinstance(value, dict):
        return ""
    for key in keys:
        item = value.get(key)
        if item is not None and item != "":
            return str(item)
    return ""


def collect_paginated_items(profile, path):
    items = []
    offset = 0
    has_more = False
    first_payload = None
    last_error = ""
    for _ in range(max(1, API_MAX_PAGES)):
        page_path = "%s?limit=%d&offset=%d" % (path, API_PAGE_LIMIT, offset)
        payload, err = http_json(profile, page_path)
        if payload is None and offset == 0:
            payload, err = http_json(profile, path)
        if payload is None:
            last_error = err
            break
        if first_payload is None:
            first_payload = payload
        page_items = list_items(payload)
        items.extend(page_items)
        if not isinstance(payload, dict):
            has_more = False
            break
        has_more = bool(payload.get("has_more"))
        if not has_more or not page_items:
            break
        next_offset = payload.get("offset")
        page_limit = payload.get("limit")
        try:
            offset = int(next_offset or offset) + int(page_limit or len(page_items))
        except Exception:
            offset += len(page_items)
    return items, has_more, first_payload, last_error


def collect_api(profile):
    api = {
        "base_url": api_base_url(profile),
        "enabled": bool(api_base_url(profile)),
        "status": "unknown",
        "errors": [],
    }
    health, err = http_json(profile, "/health")
    if health is None:
        api["errors"].append("health: %s" % err)
    else:
        api["status"] = first_string(health, ("status", "state", "health")) or "ok"
        api["health"] = health

    detailed, err = http_json(profile, "/health/detailed")
    if detailed is not None:
        api["detailed_health"] = detailed
    elif err:
        api["errors"].append("health/detailed: %s" % err)

    jobs_payload, err = http_json(profile, "/api/jobs")
    jobs = []
    api_usage = {}
    if jobs_payload is not None:
        api_usage = usage_add(api_usage, usage_sum(jobs_payload))
        for item in list_items(jobs_payload)[:MAX_TABLE_ROWS]:
            if not isinstance(item, dict):
                continue
            enabled = item.get("enabled")
            paused = item.get("paused")
            status = "paused" if paused else ("enabled" if enabled is not False else "disabled")
            jobs.append({
                "profile": profile,
                "job_id": first_string(item, ("job_id", "id", "name")),
                "name": first_string(item, ("name", "title", "job_id", "id")),
                "schedule": first_string(item, ("schedule", "cron")),
                "next_run_at": first_string(item, ("next_run_at", "next_run")),
                "status": status,
                "enabled": bool(enabled is not False and not paused),
                "last_run_at": first_string(item, ("last_run_at", "last_run")),
                "last_status": first_string(item, ("last_status", "status", "state")),
                "last_error": first_string(item, ("last_error", "error")),
                "skills": first_string(item, ("skills", "skill")),
                "provider": first_string(item, ("provider",)),
                "model": first_string(item, ("model",)),
                "delivery": first_string(item, ("delivery",)),
                "no_agent": bool(item.get("no_agent") or item.get("no-agent")),
            })
    elif err:
        api["errors"].append("jobs: %s" % err)

    sessions = []
    sessions_total_count = 0
    sessions_has_more = False
    session_items, sessions_has_more, sessions_payload, err = collect_paginated_items(profile, "/api/sessions")
    if sessions_payload is not None:
        api_usage = usage_add(api_usage, usage_sum(session_items))
        sessions_total_count = len(session_items)
        if isinstance(sessions_payload, dict):
            declared = sessions_payload.get("total") or sessions_payload.get("total_count") or sessions_payload.get("count")
            try:
                sessions_total_count = max(sessions_total_count, int(declared or 0))
            except Exception:
                pass
        for item in session_items[:MAX_TABLE_ROWS]:
            if not isinstance(item, dict):
                continue
            session_usage = usage_from(item)
            sessions.append({
                "profile": profile,
                "session_id": first_string(item, ("id", "session_id")),
                "title": first_string(item, ("title", "name")),
                "status": first_string(item, ("status", "state")),
                "message_count": int(item.get("message_count") or item.get("messages_count") or 0),
                "parent_id": first_string(item, ("parent_id", "forked_from", "source_session_id")),
                "updated_at": first_string(item, ("updated_at", "last_message_at", "created_at")),
                "usage": session_usage,
            })
    elif err:
        api["errors"].append("sessions: %s" % err)

    capabilities = {}
    toolsets_payload = None
    toolsets_error = ""
    for key, path in (("models", "/v1/models"), ("capabilities", "/v1/capabilities"), ("skills", "/v1/skills"), ("toolsets", "/v1/toolsets")):
        payload, err = http_json(profile, path)
        if payload is None:
            if err:
                api["errors"].append("%s: %s" % (key, err))
                if key == "toolsets":
                    toolsets_error = err
            continue
        if key == "toolsets":
            toolsets_payload = payload
        capabilities[key] = list_items(payload)[:MAX_TABLE_ROWS] or payload

    api["jobs"] = jobs
    api["sessions"] = sessions
    api["sessions_total_count"] = sessions_total_count
    api["sessions_has_more"] = sessions_has_more
    api["usage"] = api_usage
    api["capabilities"] = capabilities
    api["mixture_of_agents"] = mixture_of_agents_from_toolsets(toolsets_payload)
    if toolsets_error:
        api["mixture_of_agents"]["error"] = toolsets_error
    return api


def run_files(profile_dir):
    files = list((profile_dir / "logs").glob("**/*.json"))
    files += list((profile_dir / "logs").glob("**/run.json"))
    unique = {}
    for path in files:
        unique[str(path)] = path
    return sorted(unique.values(), key=lambda p: p.stat().st_mtime if p.exists() else 0)


def profile_stats(profile, profile_dir):
    today = dt.datetime.now().date()
    yesterday = today - dt.timedelta(days=1)
    success = 0
    total = 0
    tokens = 0
    usage_estimate = {}
    last_run = ""
    last_mtime = 0

    for path in run_files(profile_dir):
        try:
            mtime = path.stat().st_mtime
        except Exception:
            continue
        data = load_json(path)
        when = json_times(data) or dt.datetime.fromtimestamp(mtime)
        if mtime > last_mtime:
            last_mtime = mtime
            last_run = dt.datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds")
        if when.date() != yesterday:
            continue
        total += 1
        if is_success(data):
            success += 1
        tokens += token_sum(data)
        usage_estimate = usage_add(usage_estimate, usage_sum(data))

    state, unit = service_status(profile)
    cli = parse_cli_status(hermes_cli_status(profile))
    api = collect_api(profile)
    active_jobs = sum(1 for job in api.get("jobs", []) if job.get("enabled"))
    total_jobs = len(api.get("jobs", []))
    if not total_jobs:
        active_jobs = cli.get("scheduled_jobs_active", 0)
        total_jobs = cli.get("scheduled_jobs_total", 0)
    sessions = api.get("sessions", [])
    active_sessions = sum(1 for item in sessions if str(item.get("status", "")).lower() in ("active", "running", "streaming"))
    sessions_total = int(api.get("sessions_total_count") or len(sessions))
    sessions_has_more = bool(api.get("sessions_has_more"))
    if not sessions_total:
        active_sessions = cli.get("active_sessions", 0)
        sessions_total = cli.get("sessions_total", 0)

    detailed = api.get("detailed_health") or {}
    health = api.get("health") or {}
    usage = api.get("usage") or usage_from(detailed) or usage_from(health)
    if usage and not usage.get("total_tokens"):
        usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    if not usage and usage_estimate:
        usage = usage_estimate
        if not usage.get("total_tokens"):
            usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        usage["estimated"] = True
    if not usage and tokens:
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": tokens, "estimated": True}
    if not usage:
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "estimated": True}

    model = cli.get("model") or find_model(profile_dir)
    provider = cli.get("provider") or first_string(detailed, ("provider",)) or first_string(health, ("provider",))
    config_summary = summarize_config(
        profile=profile,
        hermes_root=str(HERMES_ROOT),
        profile_dir=str(profile_dir),
        config_path=profile_config_path_for(profile),
    )
    payload = {
        "profile": profile,
        "agent_version": hermes_agent_version(),
        "api_status": api.get("status", "unknown"),
        "api_base_url": api.get("base_url", ""),
        "service_status": api.get("status") or cli.get("service_status") or state,
        "service_unit": unit,
        "gateway_service": cli.get("gateway_service") or state,
        "manager_mode": cli.get("manager_mode", ""),
        "usage_mode": cli.get("usage_mode", ""),
        "provider": provider,
        "model": model,
        "auth_refreshed_at": cli.get("auth_refreshed_at", ""),
        "scheduled_jobs_active": active_jobs,
        "scheduled_jobs_total": total_jobs,
        "sessions_active": active_sessions,
        "sessions_total": sessions_total,
        "sessions_has_more": sessions_has_more,
        "running_agents": int((detailed.get("running_agents") if isinstance(detailed, dict) else 0) or (health.get("running_agents") if isinstance(health, dict) else 0) or 0),
        "resource_status": first_string(detailed, ("resource_status", "resources_status")) or first_string(health, ("resource_status", "resources_status")),
        "usage": usage,
        "yesterday_success": success,
        "yesterday_total": total,
        "yesterday_tokens": tokens,
        "last_run_at": last_run,
        "note": "; ".join(api.get("errors", [])[:2]) or str(profile_dir),
        "jobs": api.get("jobs", []),
        "sessions": api.get("sessions", []),
        "runs": [],
        "capabilities": api.get("capabilities", {}),
        "mixture_of_agents": api.get("mixture_of_agents", {}),
        "config_summary": config_summary,
    }
    return payload


def atomic_write(path, payload):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    export_hardware()
    for profile in PROFILES:
        profile_dir = profile_dir_for(profile)
        if profile_dir.is_dir():
            payload = profile_stats(profile, profile_dir)
        else:
            payload = {
                "profile": profile,
                "agent_version": hermes_agent_version(),
                "service_status": "missing",
                "gateway_service": "missing",
                "manager_mode": "",
                "usage_mode": "",
                "provider": "",
                "model": "-",
                "auth_refreshed_at": "",
                "scheduled_jobs_active": 0,
                "scheduled_jobs_total": 0,
                "sessions_active": 0,
                "sessions_total": 0,
                "running_agents": 0,
                "usage": {},
                "last_run_at": "",
                "note": str(profile_dir),
                "jobs": [],
                "sessions": [],
                "runs": [],
                "capabilities": {},
                "mixture_of_agents": {
                    "source": "GET /v1/toolsets",
                    "available": False,
                    "name": "moa",
                    "label": "Mixture of Agents",
                    "description": "",
                    "enabled": None,
                    "configured": None,
                    "tools": [],
                },
                "config_summary": summarize_config(
                    profile=profile,
                    hermes_root=str(HERMES_ROOT),
                    profile_dir=str(profile_dir),
                    config_path=profile_config_path_for(profile),
                ),
            }
        path = OUTPUT_DIR / f"{profile}.json"
        atomic_write(path, payload)


if __name__ == "__main__":
    main()
