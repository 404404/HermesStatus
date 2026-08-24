#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SCRIPT_DIR = Path(__file__).resolve().parent
CLIENT_DIR = SCRIPT_DIR.parent / "clients"
if CLIENT_DIR.is_dir() and str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from secure_file import SecureFileError, secure_read_bounded_regular_file

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - exercised by local fallback tests
    yaml = None


SENSITIVE_KEYWORDS = ("api_key", "token", "secret", "password", "credential", "auth")
SECRET_PATH_PATTERN = re.compile(
    r"(^|/)(\.env(?:$|[.:/])|[^/:]*(secret|token|credential|password|auth)[^/:]*)(?:$|[/:])",
    re.I,
)
SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(authorization\s*:|\bbearer\s+\S+|(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|password|passwd|secret|credential)\s*[:=]|[?&](api[_-]?key|key|token|password)=)"
)
AUXILIARY_KEYS = (
    "vision",
    "web_extract",
    "compression",
    "skills_hub",
    "approval",
    "mcp",
    "title_generation",
    "triage_specifier",
    "kanban_decomposer",
    "profile_describer",
    "curator",
)
MAX_PROVIDER = 128
MAX_MODEL = 256
MAX_URL = 256
MAX_NAME = 64
MAX_VOLUME = 512
MAX_COUNTER = 1000000000
MAX_DURATION = 86400.0
MAX_HERMES_CONFIG_BYTES = 2 << 20


def _string(value):
    if value is None:
        return ""
    return str(value)


def bounded(value, limit):
    return _string(value).strip()[:limit]


def public_text(value, limit):
    text = bounded(value, limit)
    return "[redacted]" if SECRET_VALUE_PATTERN.search(text) else text


def optional_integer(value):
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if 0 <= number <= MAX_COUNTER else None


def optional_duration(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if 0 <= number <= MAX_DURATION else None


def _bool(value):
    return bool(value) if value is not None else False


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def _scalar(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return ""
    if text in ("[]", "{}"):
        return [] if text == "[]" else {}
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part.strip()) for part in inner.split(",")]
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    lower = text.lower()
    if lower in ("true", "yes", "on"):
        return True
    if lower in ("false", "no", "off"):
        return False
    if lower in ("null", "none", "~"):
        return None
    try:
        return int(text)
    except Exception:
        pass
    try:
        return float(text)
    except Exception:
        return text


def _parse_simple_yaml(text):
    """Small mapping/list parser used only when PyYAML is unavailable locally."""
    root = {}
    stack = [(-1, root)]
    lines = text.splitlines()
    for line_index, raw in enumerate(lines):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            if not isinstance(parent, list):
                raise ValueError("list item is not under a list")
            parent.append(_scalar(line[2:]))
            continue
        if ":" not in line:
            raise ValueError("expected key: value")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            next_is_list = False
            for next_raw in lines[line_index + 1:]:
                if not next_raw.strip() or next_raw.lstrip().startswith("#"):
                    continue
                next_indent = len(next_raw) - len(next_raw.lstrip(" "))
                next_is_list = next_indent > indent and next_raw.strip().startswith("- ")
                break
            next_obj = [] if next_is_list else {}
            parent[key] = next_obj
            stack.append((indent, next_obj))
        else:
            parent[key] = _scalar(value)
    return root


def parse_yaml_file(path):
    data = secure_read_bounded_regular_file(
        str(Path(path)),
        MAX_HERMES_CONFIG_BYTES,
    )
    text = data.decode("utf-8", errors="replace")
    if yaml is not None:
        data = yaml.safe_load(text)
    else:
        data = _parse_simple_yaml(text)
    return data if isinstance(data, dict) else {}


def sensitive_key(key):
    lower = str(key or "").lower()
    return any(word in lower for word in SENSITIVE_KEYWORDS)


def configured(value):
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict)):
        return bool(value)
    return bool(value)


def sensitive_flags(mapping):
    flags = {}
    for key, value in _dict(mapping).items():
        if not sensitive_key(key):
            continue
        name = "%s_configured" % str(key).strip().lower().replace("-", "_")
        has_value = configured(value)
        flags[name] = has_value
        if has_value:
            flags["%s_source" % name[:-11]] = "config"
    return flags


def model_display(provider, model, empty_display=""):
    provider = _string(provider).strip()
    model = _string(model).strip()
    if provider.lower() == "auto" and not model:
        return "Auto / inherit"
    if provider and not model:
        return "%s / default" % provider
    if provider and model:
        return "%s / %s" % (provider, model)
    if model:
        return model
    return empty_display


def base_url_display(base_url):
    value = _string(base_url).strip()
    if not value:
        return "provider default"
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return "provider default"
        host = parsed.hostname
        if parsed.port:
            host = "%s:%d" % (host, parsed.port)
        return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))[:MAX_URL]
    except (TypeError, ValueError):
        return "provider default"


def safe_volume(value):
    text = _string(value).strip()
    if not text or len(text) > MAX_VOLUME or SECRET_PATH_PATTERN.search(text):
        return ""
    return text


def empty_summary(config_found=False):
    return {
        "config_found": bool(config_found),
        "main_model": {
            "provider": "",
            "model": "",
            "base_url": "provider default",
            "concurrency": None,
            "timeout_seconds": None,
        },
        "auxiliary_models": [],
        "delegation": {
            "provider": "",
            "model": "",
            "base_url": "provider default",
            "reasoning_effort": "",
            "max_concurrent_children": None,
            "max_spawn_depth": None,
            "child_timeout_seconds": None,
        },
        "docker_volumes": [],
    }


def sanitize_summary_snapshot(value):
    value = _dict(value)
    result = empty_summary(value.get("config_found") is True)
    main = _dict(value.get("main_model"))
    result["main_model"] = {
        "provider": public_text(main.get("provider"), MAX_PROVIDER),
        "model": public_text(main.get("model"), MAX_MODEL),
        "base_url": base_url_display(main.get("base_url")),
        "concurrency": optional_integer(main.get("concurrency")),
        "timeout_seconds": optional_duration(main.get("timeout_seconds")),
    }
    auxiliary = []
    for raw in _list(value.get("auxiliary_models"))[:len(AUXILIARY_KEYS)]:
        item = _dict(raw)
        name = bounded(item.get("name"), MAX_NAME)
        if name not in AUXILIARY_KEYS:
            continue
        source = bounded(item.get("source"), MAX_NAME)
        if source not in ("config", "main_model"):
            source = "config"
        auxiliary.append({
            "name": name,
            "provider": public_text(item.get("provider"), MAX_PROVIDER),
            "model": public_text(item.get("model"), MAX_MODEL),
            "effective_provider": public_text(item.get("effective_provider"), MAX_PROVIDER),
            "effective_model": public_text(item.get("effective_model"), MAX_MODEL),
            "source": source,
            "base_url_display": base_url_display(item.get("base_url_display")),
            "timeout_seconds": optional_duration(item.get("timeout_seconds")),
            "download_timeout_seconds": optional_duration(item.get("download_timeout_seconds")),
            "max_concurrency": optional_integer(item.get("max_concurrency")),
            "language": public_text(item.get("language"), MAX_NAME),
            "extra_body_configured": bool(item.get("extra_body_configured")),
            "credential_configured": bool(item.get("credential_configured")),
        })
    result["auxiliary_models"] = auxiliary
    delegation = _dict(value.get("delegation"))
    result["delegation"] = {
        "provider": public_text(delegation.get("provider"), MAX_PROVIDER),
        "model": public_text(delegation.get("model"), MAX_MODEL),
        "base_url": base_url_display(delegation.get("base_url")),
        "reasoning_effort": public_text(delegation.get("reasoning_effort"), MAX_NAME),
        "max_concurrent_children": optional_integer(delegation.get("max_concurrent_children")),
        "max_spawn_depth": optional_integer(delegation.get("max_spawn_depth")),
        "child_timeout_seconds": optional_duration(delegation.get("child_timeout_seconds")),
    }
    result["docker_volumes"] = [
        item for item in (safe_volume(raw) for raw in _list(value.get("docker_volumes"))) if item
    ][:64]
    return result


def config_candidates(profile=None, env=None, home=None, hermes_root=None, profile_dir=None, config_path=None):
    env = env or os.environ
    home = home or env.get("HOME") or str(Path.home())
    hermes_root = Path(hermes_root or env.get("HERMES_ROOT", "/home/hermes"))
    paths = []
    if config_path:
        paths.append(config_path)
    profile_key = ""
    if profile:
        profile_key = "HERMES_CONFIG_PATH_%s" % "".join(ch if ch.isalnum() else "_" for ch in profile.upper())
        if env.get(profile_key):
            paths.append(env.get(profile_key))
    if env.get("HERMES_CONFIG_PATH"):
        paths.append(env.get("HERMES_CONFIG_PATH"))
    if profile:
        paths.append(str(hermes_root / ".hermes" / "profiles" / profile / "config.yaml"))
        paths.append(str(hermes_root / ".hermes" / profile / "config.yaml"))
    if profile_dir:
        paths.append(str(Path(profile_dir) / "config.yaml"))
    paths.extend([
        "/opt/data/config.yaml",
        "/root/.hermes/config.yaml",
        str(Path(home) / ".hermes" / "config.yaml"),
    ])
    deduped = []
    seen = set()
    for item in paths:
        if not item or item in seen:
            continue
        deduped.append(item)
        seen.add(item)
    return deduped


def summarize_config_data(data, config_path=""):
    data = _dict(data)
    model = _dict(data.get("model"))
    model_value = public_text(model.get("model") or model.get("default"), MAX_MODEL)
    main_model = {
        "provider": public_text(model.get("provider"), MAX_PROVIDER),
        "model": model_value,
        "base_url": base_url_display(model.get("base_url")),
        "concurrency": optional_integer(model.get("max_concurrency", model.get("concurrency"))),
        "timeout_seconds": optional_duration(model.get("timeout")),
    }

    auxiliary = []
    auxiliary_data = _dict(data.get("auxiliary"))
    for key in AUXILIARY_KEYS:
        if key not in auxiliary_data:
            continue
        value = auxiliary_data.get(key)
        item = _dict(value)
        provider = public_text(item.get("provider"), MAX_PROVIDER)
        aux_model = public_text(item.get("model"), MAX_MODEL)
        base_url = _string(item.get("base_url"))
        inherits_main = provider.strip().lower() == "auto" and not aux_model.strip()
        configured_model = provider.strip().lower() != "auto" and bool(aux_model.strip())
        if not inherits_main and not configured_model:
            continue
        display_provider = main_model["provider"] if inherits_main else provider
        display_model = main_model["model"] if inherits_main else aux_model
        display_base_url = main_model["base_url"] if inherits_main else base_url
        summary = {
            "name": key,
            "provider": provider,
            "model": aux_model,
            "effective_provider": display_provider,
            "effective_model": display_model,
            "source": "main_model" if inherits_main else "config",
            "base_url_display": base_url_display(display_base_url),
            "timeout_seconds": optional_duration(item.get("timeout")),
            "download_timeout_seconds": optional_duration(item.get("download_timeout")),
            "max_concurrency": optional_integer(item.get("max_concurrency")),
            "language": public_text(item.get("language"), MAX_NAME),
            "extra_body_configured": configured(item.get("extra_body")),
            "credential_configured": any(configured(value) for name, value in item.items() if sensitive_key(name)),
        }
        auxiliary.append(summary)

    delegation = _dict(data.get("delegation"))
    delegation_provider = public_text(delegation.get("provider"), MAX_PROVIDER)
    delegation_model = public_text(delegation.get("model"), MAX_MODEL)
    delegation_summary = {
        "provider": delegation_provider,
        "model": delegation_model,
        "base_url": base_url_display(delegation.get("base_url")),
        "reasoning_effort": public_text(delegation.get("reasoning_effort"), MAX_NAME),
        "max_concurrent_children": optional_integer(delegation.get("max_concurrent_children")),
        "max_spawn_depth": optional_integer(delegation.get("max_spawn_depth")),
        "child_timeout_seconds": optional_duration(delegation.get("child_timeout_seconds")),
    }

    return {
        "config_found": True,
        "main_model": main_model,
        "auxiliary_models": auxiliary,
        "delegation": delegation_summary,
        "docker_volumes": [item for item in (safe_volume(value) for value in _list(_dict(data.get("terminal")).get("docker_volumes"))) if item][:64],
    }


def summarize_config(profile=None, env=None, home=None, hermes_root=None, profile_dir=None, config_path=None, return_source=False):
    """Return a sanitized config summary.

    ``return_source`` is an internal exporter-only option.  It returns the
    successfully parsed regular-file path alongside the summary so the caller
    can derive local freshness metadata without putting host paths into the
    persisted/public summary.
    """
    checked = config_candidates(
        profile=profile,
        env=env,
        home=home,
        hermes_root=hermes_root,
        profile_dir=profile_dir,
        config_path=config_path,
    )
    for path in checked:
        try:
            summary = summarize_config_data(parse_yaml_file(path), path)
            return (summary, str(path)) if return_source else summary
        except SecureFileError:
            continue
        except Exception:
            summary = empty_summary(True)
            return (summary, None) if return_source else summary
    summary = empty_summary(False)
    return (summary, None) if return_source else summary


def main():
    profile = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(summarize_config(profile=profile), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
