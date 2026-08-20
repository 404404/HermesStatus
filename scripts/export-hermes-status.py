#!/usr/bin/env python3
import datetime as dt
import http.client
import json
import os
import re
import socket
import subprocess
import sys
from urllib.parse import urlparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
CLIENT_DIR = SCRIPT_DIR.parent / "clients"
if CLIENT_DIR.is_dir() and str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from hermes_config_summary import sanitize_summary_snapshot, summarize_config
from secure_file import SecureFileError, secure_read_bounded_regular_file


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _string(value):
    return "" if value is None else str(value)


EXTENSION_VERSION = "1.0-draft"
TRUE_VALUES = {"1", "true", "yes", "on"}
MAX_PROFILES = 64
MAX_PROFILE_NAME = 64
API_PAGE_LIMIT = 100
API_MAX_PAGES = 100
API_TIMEOUT = 2.5
HOST_USER = "hermes"
PROFILE_ENV_CACHE = {}
HERMES_VERSION_CACHE = None
EXPORT_CONFIG_PATH = os.environ.get("HERMES_EXPORT_CONFIG", "/app/hermes-exporter.json")
MAX_STRING = 256
MAX_MODEL = 256
MAX_PROVIDER = 128
MAX_COUNTER = 9007199254740991
MAX_PROFILE_COUNTER = 1000000000
SECRET_TEXT_PATTERN = re.compile(
    r"(?i)(authorization\s*:|\bbearer\s+\S+|(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|password|passwd|secret|credential)\s*[:=]|--(token|password)(=|\s+)|[?&](api[_-]?key|key|token|password)=)"
)
MAX_EXPORT_CONFIG_BYTES = 1 << 20
MAX_PROFILE_ENV_BYTES = 64 << 10
MAX_PROFILE_TEXT_BYTES = 2 << 20


def secure_read_text(path, maximum, errors="replace"):
    try:
        data = secure_read_bounded_regular_file(str(Path(path)), maximum)
        return data.decode("utf-8", errors=errors)
    except (SecureFileError, UnicodeError):
        return None


def utc_timestamp(now=None):
    value = now or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_timestamp(value):
    text = _string(value).strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\s+[A-Za-z0-9_+/-]+)?$", text)
        if not match:
            return None
        try:
            parsed = dt.datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return utc_timestamp(parsed)


def safe_error(code, message, source="hermes-integration", retryable=False, http_status=None):
    return {
        "code": re.sub(r"[^a-z0-9_]+", "_", _string(code).lower()).strip("_")[:64] or "source_error",
        "message": _string(message)[:256] or "Hermes data is unavailable",
        "source": re.sub(r"[^A-Za-z0-9_.-]+", "-", _string(source))[:64] or "hermes-integration",
        "retryable": bool(retryable),
        "http_status": http_status if isinstance(http_status, int) and 100 <= http_status <= 599 else None,
    }


def unavailable_usage():
    return {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "estimated": True,
        "source": "unavailable",
        "window_start": None,
        "window_end": None,
    }


def bounded_text(value, limit=MAX_STRING):
    return _string(value).strip()[:limit]


def public_text(value, limit=MAX_STRING):
    text = bounded_text(value, limit)
    return "[redacted]" if SECRET_TEXT_PATTERN.search(text) else text


def safe_counter(value):
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if 0 <= number <= MAX_COUNTER else None


def safe_profile_counter(value):
    number = safe_counter(value)
    return number if number is not None and number <= MAX_PROFILE_COUNTER else None


def usage_payload(value, estimated, source, window_start=None, window_end=None):
    value = _dict(value)
    input_tokens = safe_counter(value.get("input_tokens"))
    output_tokens = safe_counter(value.get("output_tokens"))
    total_tokens = safe_counter(value.get("total_tokens"))
    if input_tokens is None or output_tokens is None:
        return unavailable_usage()
    calculated_total = input_tokens + output_tokens
    if calculated_total > MAX_COUNTER:
        return unavailable_usage()
    if total_tokens is None or total_tokens != calculated_total:
        total_tokens = calculated_total
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated": bool(estimated),
        "source": source,
        "window_start": normalize_timestamp(window_start),
        "window_end": normalize_timestamp(window_end),
    }


def load_export_config():
    path = os.environ.get("HERMES_EXPORT_CONFIG") or EXPORT_CONFIG_PATH
    if not path:
        return {}
    config_path = Path(path)
    text = secure_read_text(config_path, MAX_EXPORT_CONFIG_BYTES)
    if text is None:
        return {}
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
    seen = set()
    for item in _list(raw):
        if isinstance(item, str):
            item = {"name": item}
        item = _dict(item)
        name = _string(item.get("name") or item.get("profile")).strip()
        if not name or name in seen or len(name) > MAX_PROFILE_NAME or not re.match(r"^[A-Za-z0-9_.-]+$", name):
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
        seen.add(name)
    return profiles[:MAX_PROFILES]


EXPORT_CONFIG = {}
CONFIG_HAS_PROFILES = False
HERMES_ROOT = Path("/home/hermes")
OUTPUT_DIR = Path("/var/lib/serverstatus-client/hermes")
PROFILE_CONFIGS = []
PROFILE_BY_NAME = {}
PROFILES = []
DEFAULT_PORTS = {}


def refresh_runtime_config():
    global EXPORT_CONFIG, CONFIG_HAS_PROFILES, HERMES_ROOT, OUTPUT_DIR
    global PROFILE_CONFIGS, PROFILE_BY_NAME, PROFILES, DEFAULT_PORTS
    global API_TIMEOUT, API_PAGE_LIMIT, API_MAX_PAGES, HOST_USER
    EXPORT_CONFIG = load_export_config()
    HERMES_ROOT = Path(env_or_config("HERMES_ROOT", EXPORT_CONFIG, "hermes_root", "/home/hermes"))
    OUTPUT_DIR = Path(env_or_config("HERMES_STATUS_DIR", EXPORT_CONFIG, "status_dir", "/var/lib/serverstatus-client/hermes"))
    PROFILE_CONFIGS = normalize_profiles(EXPORT_CONFIG, HERMES_ROOT)
    PROFILE_BY_NAME = {item["name"]: item for item in PROFILE_CONFIGS}
    PROFILES = [item["name"] for item in PROFILE_CONFIGS]
    CONFIG_HAS_PROFILES = bool(PROFILE_CONFIGS)
    DEFAULT_PORTS = {}
    for item in PROFILE_CONFIGS:
        raw_port = item.get("api_port") or _dict(item.get("api")).get("port")
        try:
            if raw_port is not None and str(raw_port).strip():
                DEFAULT_PORTS[item["name"]] = int(raw_port)
        except (TypeError, ValueError):
            continue
    try:
        API_TIMEOUT = max(0.1, min(30.0, float(os.environ.get("HERMES_API_TIMEOUT", "2.5"))))
    except ValueError:
        API_TIMEOUT = 2.5
    try:
        API_PAGE_LIMIT = max(1, min(500, int(os.environ.get("HERMES_API_PAGE_LIMIT", "100"))))
        API_MAX_PAGES = max(1, min(100, int(os.environ.get("HERMES_API_MAX_PAGES", "100"))))
    except ValueError:
        API_PAGE_LIMIT, API_MAX_PAGES = 100, 100
    HOST_USER = os.environ.get("HERMES_HOST_USER", "hermes")
    PROFILE_ENV_CACHE.clear()


refresh_runtime_config()


def profile_config(profile):
    return PROFILE_BY_NAME.get(profile, {})


def profile_dir_for(profile):
    return Path(profile_config(profile).get("profile_dir") or (HERMES_ROOT / profile))


def profile_config_path_for(profile):
    return _string(profile_config(profile).get("config_path")).strip()


def profile_config_refreshed_at(profile):
    path = profile_config_path_for(profile)
    if not path:
        return None
    try:
        modified = Path(path).stat().st_mtime
    except OSError:
        return None
    return utc_timestamp(dt.datetime.fromtimestamp(modified, tz=dt.timezone.utc))


def run_text(cmd, timeout=8):
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            env=dict(os.environ, LC_ALL="C"),
        )
        return proc.stdout[:300000].strip()
    except (OSError, subprocess.SubprocessError):
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
        text = secure_read_text(path, MAX_PROFILE_ENV_BYTES, errors="ignore")
        if text is None:
            raise ValueError("profile environment unavailable")
        for line in text.splitlines():
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
    return "http://127.0.0.1:%d" % port if port else ""


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
        return None, safe_error("api_disabled", "Hermes API is not configured", "hermes-api")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None, safe_error("api_config_invalid", "Hermes API configuration is invalid", "hermes-api")
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    body = None
    headers = {"Accept": "application/json"}
    token = api_token(profile)
    if not token:
        return None, safe_error("api_unauthorized", "Hermes API authorization is unavailable", "hermes-api", False, 401)
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
            code = "api_unauthorized" if res.status in (401, 403) else "api_http_error"
            return None, safe_error(code, "Hermes API request failed", "hermes-api", res.status >= 500, res.status)
        if not raw:
            return {}, None
        try:
            decoded = json.loads(raw.decode("utf-8", errors="replace"))
        except (TypeError, ValueError):
            return None, safe_error("api_invalid_json", "Hermes API returned invalid JSON", "hermes-api", True, res.status)
        if not isinstance(decoded, (dict, list)):
            return None, safe_error("api_invalid_json", "Hermes API returned an unsupported JSON value", "hermes-api", True, res.status)
        return decoded, None
    except (socket.timeout, TimeoutError):
        return None, safe_error("api_timeout", "Hermes API request timed out", "hermes-api", True)
    except (OSError, http.client.HTTPException):
        return None, safe_error("api_unavailable", "Hermes API is unavailable", "hermes-api", True)


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
    HERMES_VERSION_CACHE = bounded_text(version.group(0).lstrip("v") if version else value, 64)
    return HERMES_VERSION_CACHE


def provider_usage_mode(provider):
    identity = re.sub(r"[^a-z0-9]+", "", _string(provider).lower())
    return {
        "nousportal": "auth_provider",
        "openaicodex": "auth_provider",
        "xaioauth": "auth_provider",
        "supergrok": "auth_provider",
        "githubcopilot": "auth_provider",
        "qwenoauth": "auth_provider",
        "opencodego": "api",
        "openrouter": "api",
        "googleaistudio": "api",
        "deepseek": "api",
        "zaiglm": "api",
        "stepfunstepplan": "api",
        "opencodezen": "api",
    }.get(identity, "unknown")


def parse_cli_status(text):
    result = {}
    if not text:
        return result
    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text)

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
            result["model"] = bounded_text(line.split(":", 1)[1], MAX_MODEL)
        elif line.lower().startswith("provider:"):
            result["provider"] = bounded_text(line.split(":", 1)[1], MAX_PROVIDER)

    for line in sections.get("gateway service", []):
        if line.lower().startswith("status:"):
            result["gateway_service"] = bounded_text(clean_status(line.split(":", 1)[1]), 64)
        elif line.lower().startswith("manager:"):
            result["manager_mode"] = bounded_text(clean_status(line.split(":", 1)[1]), 96)

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

    configured_api_key_providers = []
    for line in sections.get("api-key providers", []):
        if "✓" not in line or "not configured" in line.lower():
            continue
        provider_name = line.split("✓", 1)[0].strip()
        if provider_name:
            configured_api_key_providers.append(provider_name)

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
    result["configured_api_key_providers"] = configured_api_key_providers
    result["auth_providers"] = auth_providers

    def provider_identity(value):
        return re.sub(r"[^a-z0-9]+", "", _string(value).lower())

    provider_aliases = {
        "googleaistudio": {"googlegemini"},
        "openai": {"openai"},
        "openaicodex": {"openaicodex"},
        "openrouter": {"openrouter"},
        "deepseek": {"deepseek"},
        "xai": {"xaigrok"},
        "nvidianim": {"nvidianim"},
        "kimi": {"kimimoonshot"},
        "moonshotai": {"kimimoonshot"},
        "zaiglm": {"zaiglm"},
        "minimax": {"minimax"},
        "minimaxchina": {"minimaxchina"},
        "anthropic": {"anthropic"},
        "stepfunstepplan": {"stepfunstepplan"},
    }
    def provider_matches(current, candidate):
        current_id = provider_identity(current)
        candidate_id = provider_identity(candidate)
        if not current_id or not candidate_id:
            return False
        if current_id == candidate_id:
            return True
        return candidate_id in provider_aliases.get(current_id, set())

    provider = result.get("provider", "")
    matching_auth = next(
        (item for item in auth_providers if provider_matches(provider, item.get("name"))),
        None,
    )
    matching_api = next(
        (
            name
            for name in api_key_providers + configured_api_key_providers
            if provider_matches(provider, name)
        ),
        None,
    )
    if matching_auth:
        result["usage_mode"] = "auth_provider"
        result["auth_refreshed_at"] = matching_auth.get("refreshed", "")
    elif matching_api:
        result["usage_mode"] = "api"
    else:
        result["usage_mode"] = provider_usage_mode(provider)

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
            text = secure_read_text(path, MAX_PROFILE_TEXT_BYTES, errors="ignore")
            if text is None:
                continue
            for line in text.splitlines():
                for pattern in patterns:
                    match = pattern.search(line)
                    if match:
                        value = match.group(1).strip().strip(",")
                        if value and value not in ("''", '""'):
                            found.append(value)
        except Exception:
            continue
    return found[-1] if found else "-"


def load_json(path):
    try:
        text = secure_read_text(path, MAX_PROFILE_TEXT_BYTES, errors="ignore")
        return json.loads(text) if text is not None else None
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
    prompt = safe_counter(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    completion = safe_counter(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    if prompt is None or completion is None or prompt + completion > MAX_COUNTER:
        return {}
    return {"input_tokens": prompt, "output_tokens": completion, "total_tokens": prompt + completion}


def usage_add(left, right):
    if not right:
        return left
    out = dict(left or {})
    input_tokens = safe_counter(out.get("input_tokens") or 0)
    output_tokens = safe_counter(out.get("output_tokens") or 0)
    right_input = safe_counter(right.get("input_tokens") or 0)
    right_output = safe_counter(right.get("output_tokens") or 0)
    if None in (input_tokens, output_tokens, right_input, right_output):
        return out
    input_tokens += right_input
    output_tokens += right_output
    if input_tokens + output_tokens > MAX_COUNTER:
        return out
    out["input_tokens"] = input_tokens
    out["output_tokens"] = output_tokens
    out["total_tokens"] = input_tokens + output_tokens
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


def run_snapshot_files(profile_dir):
    paths = list((profile_dir / "logs").glob("**/*.json"))
    unique = {}
    for path in paths:
        try:
            unique[str(path)] = (path.stat().st_mtime, path)
        except OSError:
            continue
    return [item[1] for item in sorted(unique.values(), key=lambda item: item[0])]


def collect_local_usage(profile_dir, now=None):
    local_now = now or dt.datetime.now().astimezone()
    if local_now.tzinfo is None:
        local_now = local_now.astimezone()
    window_end_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start_local = window_end_local - dt.timedelta(days=1)
    total = {}
    for path in run_snapshot_files(profile_dir):
        data = load_json(path)
        if not isinstance(data, (dict, list)):
            continue
        try:
            modified = dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        except OSError:
            continue
        when = json_times(data) if isinstance(data, dict) else None
        if when is None:
            when = modified.replace(tzinfo=None)
        if when.tzinfo is None:
            when = when.astimezone()
        if not (window_start_local <= when < window_end_local):
            continue
        total = usage_add(total, usage_sum(data))
    if not total:
        return unavailable_usage()
    return usage_payload(
        total,
        True,
        "local_logs",
        utc_timestamp(window_start_local),
        utc_timestamp(window_end_local),
    )


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
        tools = [bounded_text(tool, 128) for tool in _list(item.get("tools"))[:64] if bounded_text(tool, 128)]
        name = bounded_text(first_string(item, ("name", "id", "key")), 128)
        label = bounded_text(first_string(item, ("label", "title", "display_name")), 128)
        haystack = " ".join([name, label, first_string(item, ("description",))] + tools).lower()
        if name.lower() != "moa" and "mixture_of_agents" not in tools and "mixture of agents" not in haystack:
            continue
        return {
            "source": "GET /v1/toolsets",
            "available": True,
            "name": name or "moa",
            "label": label or "Mixture of Agents",
            "description": bounded_text(first_string(item, ("description",)), 512),
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
    last_error = None
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
        "enabled": bool(api_base_url(profile)),
        "status": "unknown",
        "errors": [],
    }
    health, err = http_json(profile, "/health")
    if health is None:
        api["errors"].append(err)
    else:
        status = bounded_text(first_string(health, ("status", "state", "health")).lower(), 32)
        api["status"] = status if status in ("ok", "healthy") else "unknown"
        api["health"] = health

    detailed, err = http_json(profile, "/health/detailed")
    if detailed is not None:
        api["detailed_health"] = detailed
    elif err:
        api["errors"].append(err)

    jobs_payload, err = http_json(profile, "/api/jobs")
    api_usage = {}
    if jobs_payload is not None:
        api_usage = usage_add(api_usage, usage_sum(jobs_payload))
        job_items = [item for item in list_items(jobs_payload) if isinstance(item, dict)]
        declared_jobs = first_string(jobs_payload, ("total", "total_count", "count"))
        api["jobs_total"] = max(len(job_items), safe_counter(declared_jobs) or 0)
        api["jobs_active"] = sum(
            1 for item in job_items
            if item.get("enabled") is not False and not bool(item.get("paused"))
        )
    elif err:
        api["errors"].append(err)

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
            except (TypeError, ValueError):
                pass
        counted_active = sum(
            1 for item in session_items
            if isinstance(item, dict) and first_string(item, ("status", "state")).lower() in ("active", "running", "streaming")
        )
        declared_active = first_string(sessions_payload, ("active", "active_sessions", "active_count"))
        api["sessions_active"] = max(counted_active, safe_counter(declared_active) or 0)
    elif err:
        api["errors"].append(err)

    api["sessions_total_count"] = sessions_total_count
    api["sessions_has_more"] = sessions_has_more
    if not api_usage:
        api_usage = usage_from(detailed or {}) or usage_from(health or {})
    api["usage"] = usage_payload(api_usage, False, "hermes_api_payload") if api_usage else unavailable_usage()

    toolsets_payload, toolsets_error = http_json(profile, "/v1/toolsets")
    api["mixture_of_agents"] = mixture_of_agents_from_toolsets(toolsets_payload)
    if toolsets_error:
        api["mixture_of_agents"]["error"] = toolsets_error.get("code")
        api["errors"].append(toolsets_error)
    return api


def fallback_value(current, previous, key, default=None):
    if current is not None and current != "":
        return current
    value = _dict(previous).get(key)
    return value if value is not None and value != "" else default


def normalize_previous_usage(value):
    value = _dict(value)
    source = value.get("source")
    if source == "unavailable":
        return unavailable_usage()
    if source not in ("hermes_api_payload", "local_session_state", "local_logs"):
        return unavailable_usage()
    result = usage_payload(
        value,
        bool(value.get("estimated")),
        source,
        value.get("window_start"),
        value.get("window_end"),
    )
    if source in ("local_session_state", "local_logs"):
        result["estimated"] = True
    return result


def sanitize_mixture_of_agents(value):
    value = _dict(value)
    enabled = value.get("enabled") if isinstance(value.get("enabled"), bool) else None
    configured = value.get("configured") if isinstance(value.get("configured"), bool) else None
    tools = [public_text(item, 128) for item in _list(value.get("tools"))[:64]]
    tools = [item for item in tools if item]
    error = public_text(value.get("error"), 64) or None
    return {
        "source": public_text(value.get("source") or "GET /v1/toolsets", 64),
        "available": bool(value.get("available")),
        "name": public_text(value.get("name") or "moa", 128),
        "label": public_text(value.get("label") or "Mixture of Agents", 128),
        "description": public_text(value.get("description"), 512),
        "enabled": enabled,
        "configured": configured,
        "tools": tools,
        "error": error,
    }


def previous_profile_available(previous, profile):
    return isinstance(previous, dict) and previous.get("profile") == profile


def profile_stats(profile, profile_dir, previous=None):
    previous = _dict(previous) if previous_profile_available(previous, profile) else {}
    now = utc_timestamp()
    state, _unit = service_status(profile)
    cli = parse_cli_status(hermes_cli_status(profile))
    api = collect_api(profile)
    api_ok = isinstance(api.get("health"), dict)
    detailed = api.get("detailed_health") or {}
    health = api.get("health") or {}

    if "jobs_total" in api:
        active_jobs = safe_profile_counter(api.get("jobs_active"))
        total_jobs = safe_profile_counter(api.get("jobs_total"))
    elif "scheduled_jobs_total" in cli:
        active_jobs = safe_profile_counter(cli.get("scheduled_jobs_active"))
        total_jobs = safe_profile_counter(cli.get("scheduled_jobs_total"))
    else:
        active_jobs = safe_profile_counter(previous.get("scheduled_jobs_active"))
        total_jobs = safe_profile_counter(previous.get("scheduled_jobs_total"))

    if api_ok and api.get("sessions_total_count") is not None:
        active_sessions = safe_profile_counter(api.get("sessions_active"))
        sessions_total = safe_profile_counter(api.get("sessions_total_count"))
        sessions_has_more = bool(api.get("sessions_has_more"))
        if active_sessions == 0:
            health_active = safe_profile_counter(
                first_string(detailed, ("active_sessions", "sessions_active"))
                or first_string(health, ("active_sessions", "sessions_active"))
            )
            cli_active = safe_profile_counter(cli.get("active_sessions"))
            active_sessions = health_active if health_active is not None else (cli_active if cli_active is not None else 0)
    elif "sessions_total" in cli:
        active_sessions = safe_profile_counter(cli.get("active_sessions"))
        sessions_total = safe_profile_counter(cli.get("sessions_total"))
        sessions_has_more = False
    else:
        active_sessions = safe_profile_counter(previous.get("sessions_active"))
        sessions_total = safe_profile_counter(previous.get("sessions_total"))
        sessions_has_more = bool(previous.get("sessions_has_more"))

    usage = api.get("usage") or unavailable_usage()
    if usage.get("source") == "unavailable":
        usage = collect_local_usage(profile_dir)
    if usage.get("source") == "unavailable" and previous:
        usage = normalize_previous_usage(previous.get("usage"))

    config_summary = summarize_config(
        profile=profile,
        hermes_root=str(HERMES_ROOT),
        profile_dir=str(profile_dir),
        config_path=profile_config_path_for(profile),
    )
    if not config_summary.get("config_found") and isinstance(previous.get("config_summary"), dict):
        config_summary = sanitize_summary_snapshot(previous.get("config_summary"))
    else:
        config_summary = sanitize_summary_snapshot(config_summary)

    profile_configuration = profile_config(profile)
    model = cli.get("model") or first_string(detailed, ("model",)) or first_string(health, ("model",))
    model = fallback_value(model, previous, "model", _dict(config_summary.get("main_model")).get("model") or None)
    configured_provider = public_text(profile_configuration.get("provider_label"), MAX_PROVIDER) or None
    provider = cli.get("provider") or first_string(detailed, ("provider",)) or first_string(health, ("provider",)) or configured_provider
    provider = fallback_value(provider, previous, "provider", _dict(config_summary.get("main_model")).get("provider") or None)
    api_version = first_string(detailed, ("agent_version", "version")) or first_string(health, ("agent_version", "version"))
    version = fallback_value(api_version or hermes_agent_version(), previous, "agent_version")
    api_status = api.get("status", "unknown")
    if not api_ok and api.get("errors"):
        code = api["errors"][0].get("code")
        api_status = {
            "api_unauthorized": "unauthorized",
            "api_timeout": "timeout",
            "api_unavailable": "unavailable",
            "api_disabled": "unavailable",
        }.get(code, "error")
    # A successful /health response is the authoritative Profile health
    # signal.  Supplementary reads (jobs, sessions, or toolsets) may time out
    # independently; preserve their own bounded diagnostic state, but do not
    # contradict an otherwise healthy Profile with a stale top-level error.
    api_healthy = api_ok and api.get("status") in ("ok", "healthy")
    current_error = None if api_healthy else (api.get("errors", [None])[0] if api.get("errors") else None)
    cli_available = bool(cli)
    previous_used = not api_ok and not cli_available and bool(previous)
    updated_at = normalize_timestamp(previous.get("updated_at")) if previous_used else now
    stale = bool(previous_used or updated_at is None)
    moa = sanitize_mixture_of_agents(api.get("mixture_of_agents"))
    if (not moa or moa.get("error")) and isinstance(previous.get("mixture_of_agents"), dict):
        moa = sanitize_mixture_of_agents(previous.get("mixture_of_agents"))

    service_value = api.get("status") if api_ok else None
    if not service_value and state and state != "unknown":
        service_value = state
    gateway_value = cli.get("gateway_service") or profile_configuration.get("gateway_service")
    if not gateway_value and api_ok:
        health_status = bounded_text(first_string(health, ("status", "state", "health")).lower(), 32)
        if health_status in ("ok", "healthy"):
            gateway_value = "running"
        elif health_status:
            gateway_value = health_status
    elif not gateway_value and state and state != "unknown":
        gateway_value = state
    manager_value = cli.get("manager_mode") or profile_configuration.get("manager_mode")
    configured_usage_mode = _string(profile_configuration.get("usage_mode")).strip().lower()
    if cli_available:
        usage_mode = cli.get("usage_mode") or "unknown"
    elif configured_usage_mode in ("api", "auth_provider"):
        usage_mode = configured_usage_mode
    elif previous_used:
        usage_mode = previous.get("usage_mode") or "unknown"
    else:
        usage_mode = provider_usage_mode(provider)
    if usage_mode not in ("api", "auth_provider", "unknown"):
        usage_mode = "unknown"
    config_refreshed_at = profile_config_refreshed_at(profile)
    if cli_available:
        model_refreshed_at = normalize_timestamp(cli.get("auth_refreshed_at")) or config_refreshed_at
    elif previous_used:
        model_refreshed_at = normalize_timestamp(previous.get("auth_refreshed_at"))
    else:
        model_refreshed_at = config_refreshed_at

    payload = {
        "profile": profile,
        "agent_version": public_text(version, 64) or None,
        "api_status": api_status,
        "service_status": public_text(fallback_value(service_value, previous, "service_status"), 64) or None,
        "gateway_service": public_text(fallback_value(gateway_value, previous, "gateway_service"), 64) or None,
        "manager_mode": public_text(fallback_value(manager_value, previous, "manager_mode"), 96) or None,
        "usage_mode": usage_mode,
        "provider": public_text(provider, MAX_PROVIDER) or None,
        "model": public_text(model, MAX_MODEL) or None,
        "auth_refreshed_at": model_refreshed_at,
        "scheduled_jobs_active": active_jobs,
        "scheduled_jobs_total": total_jobs,
        "sessions_active": active_sessions,
        "sessions_total": sessions_total,
        "sessions_has_more": sessions_has_more,
        "usage": usage,
        "mixture_of_agents": moa,
        "config_summary": config_summary,
        "updated_at": updated_at,
        "received_at": now,
        "stale": stale,
        "error": current_error,
    }
    payload["auth_refreshed_at"] = normalize_timestamp(payload["auth_refreshed_at"])
    if not cli_available and not api_ok and payload["error"] is None:
        payload["error"] = safe_error("cli_unavailable", "Hermes CLI status is unavailable", "hermes-cli", True)
    return payload


def atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp), str(path))
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def main():
    refresh_runtime_config()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    profiles = []
    registered_files = set()
    for profile in PROFILES:
        profile_dir = profile_dir_for(profile)
        path = OUTPUT_DIR / (profile + ".json")
        registered_files.add(path.name)
        previous = load_json(path) or {}
        if profile_dir.is_dir():
            payload = profile_stats(profile, profile_dir, previous)
        else:
            payload = dict(previous) if previous else {
                "profile": profile,
                "agent_version": None,
                "api_status": "unavailable",
                "service_status": None,
                "gateway_service": None,
                "manager_mode": None,
                "usage_mode": "unknown",
                "provider": None,
                "model": None,
                "auth_refreshed_at": None,
                "scheduled_jobs_active": None,
                "scheduled_jobs_total": None,
                "sessions_active": None,
                "sessions_total": None,
                "sessions_has_more": False,
                "usage": unavailable_usage(),
                "mixture_of_agents": sanitize_mixture_of_agents(mixture_of_agents_from_toolsets(None)),
                "config_summary": None,
                "updated_at": None,
            }
            payload.update({
                "profile": profile,
                "received_at": utc_timestamp(),
                "stale": True,
                "error": safe_error("profile_unavailable", "Hermes profile is unavailable", "hermes-integration", True),
            })
        atomic_write(path, payload)
        profiles.append(payload)

    for path in OUTPUT_DIR.glob("*.json"):
        if path.name != "hermes.json" and path.name not in registered_files:
            try:
                path.unlink()
            except OSError:
                pass

    updated_values = [item.get("updated_at") for item in profiles if item.get("updated_at")]
    root_error = None
    if not profiles:
        root_error = safe_error("not_reported", "No Hermes profiles are registered", "hermes")
    elif any(item.get("error") for item in profiles):
        root_error = safe_error("partial_failure", "One or more Hermes profiles are unavailable", "hermes", True)
    root = {
        "extension_version": EXTENSION_VERSION,
        "profiles": profiles,
        "updated_at": max(updated_values) if updated_values else None,
        "received_at": utc_timestamp(),
        "stale": not profiles or all(bool(item.get("stale", True)) for item in profiles),
        "error": root_error,
    }
    atomic_write(OUTPUT_DIR / "hermes.json", root)
    return root


if __name__ == "__main__":
    main()
