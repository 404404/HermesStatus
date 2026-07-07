#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - exercised by local fallback tests
    yaml = None


SENSITIVE_KEYWORDS = ("api_key", "token", "secret", "password", "credential", "auth")
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


def _string(value):
    if value is None:
        return ""
    return str(value)


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
    text = Path(path).read_text(encoding="utf-8", errors="replace")
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
    return _string(base_url).strip() or "provider default"


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


def find_config_path(profile=None, env=None, home=None, hermes_root=None, profile_dir=None, config_path=None):
    checked = config_candidates(
        profile=profile,
        env=env,
        home=home,
        hermes_root=hermes_root,
        profile_dir=profile_dir,
        config_path=config_path,
    )
    for item in checked:
        try:
            if Path(item).is_file():
                return item, checked
        except OSError:
            continue
    return "", checked


def summarize_config_data(data, config_path=""):
    data = _dict(data)
    model = _dict(data.get("model"))
    model_value = _string(model.get("model") or model.get("default"))
    main_model = {
        "provider": _string(model.get("provider")),
        "model": model_value,
        "model_default": _string(model.get("default")),
        "model_model": _string(model.get("model")),
        "base_url": _string(model.get("base_url")),
    }
    main_model.update(sensitive_flags(model))

    auxiliary = {}
    auxiliary_data = _dict(data.get("auxiliary"))
    for key in AUXILIARY_KEYS:
        if key not in auxiliary_data:
            continue
        value = auxiliary_data.get(key)
        item = _dict(value)
        provider = _string(item.get("provider"))
        aux_model = _string(item.get("model"))
        base_url = _string(item.get("base_url"))
        inherits_main = provider.strip().lower() == "auto" and not aux_model.strip()
        display_provider = main_model["provider"] if inherits_main else provider
        display_model = main_model["model"] if inherits_main else aux_model
        display_base_url = main_model["base_url"] if inherits_main else base_url
        summary = {
            "provider": provider,
            "model": aux_model,
            "effective_provider": display_provider,
            "effective_model": display_model,
            "source": "main_model" if inherits_main else "config",
            "display": model_display(display_provider, display_model),
            "base_url": base_url,
            "effective_base_url": display_base_url,
            "base_url_display": base_url_display(display_base_url),
            "timeout_seconds": item.get("timeout"),
            "download_timeout_seconds": item.get("download_timeout") if "download_timeout" in item else None,
            "max_concurrency": item.get("max_concurrency") if "max_concurrency" in item else None,
            "language": _string(item.get("language")) if "language" in item else "",
            "extra_body_configured": configured(item.get("extra_body")),
        }
        summary.update(sensitive_flags(item))
        auxiliary[key] = summary

    delegation = _dict(data.get("delegation"))
    delegation_provider = _string(delegation.get("provider"))
    delegation_model = _string(delegation.get("model"))
    delegation_summary = {
        "provider": delegation_provider,
        "model": delegation_model,
        "display": model_display(delegation_provider, delegation_model, "inherit main model"),
        "base_url": _string(delegation.get("base_url")),
        "reasoning_effort": _string(delegation.get("reasoning_effort")),
        "max_concurrent_children": delegation.get("max_concurrent_children"),
        "max_spawn_depth": delegation.get("max_spawn_depth"),
        "child_timeout_seconds": delegation.get("child_timeout_seconds"),
    }
    delegation_summary.update(sensitive_flags(delegation))

    runtime_related = {
        "toolsets": _list(data.get("toolsets")),
        "platform_toolsets": _list(data.get("platform_toolsets")),
        "approvals_mode": _string(_dict(data.get("approvals")).get("mode")),
        "compression_enabled": _bool(_dict(data.get("compression")).get("enabled")),
        "memory_enabled": _bool(_dict(data.get("memory")).get("memory_enabled")),
        "curator_enabled": _bool(_dict(data.get("curator")).get("enabled")),
        "timezone": _string(data.get("timezone")),
    }

    return {
        "config_found": True,
        "config_path": _string(config_path),
        "config_version": data.get("_config_version"),
        "main_model": main_model,
        "auxiliary_models": auxiliary,
        "delegation": delegation_summary,
        "runtime_related": runtime_related,
        "docker_volumes": _list(_dict(data.get("terminal")).get("docker_volumes")),
        "warnings": [],
    }


def summarize_config(profile=None, env=None, home=None, hermes_root=None, profile_dir=None, config_path=None):
    path, checked = find_config_path(
        profile=profile,
        env=env,
        home=home,
        hermes_root=hermes_root,
        profile_dir=profile_dir,
        config_path=config_path,
    )
    if not path:
        return {
            "config_found": False,
            "error": "Hermes config.yaml not found",
            "checked_paths": checked,
            "config_path": "",
            "config_version": None,
            "main_model": {"provider": "", "model": "", "base_url": ""},
            "auxiliary_models": {},
            "delegation": {
                "provider": "",
                "model": "",
                "display": "inherit main model",
                "max_concurrent_children": None,
                "max_spawn_depth": None,
                "child_timeout_seconds": None,
            },
            "runtime_related": {
                "toolsets": [],
                "platform_toolsets": [],
                "approvals_mode": "",
                "compression_enabled": False,
                "memory_enabled": False,
                "curator_enabled": False,
                "timezone": "",
            },
            "docker_volumes": [],
            "warnings": [],
        }
    try:
        return summarize_config_data(parse_yaml_file(path), path)
    except Exception as exc:
        return {
            "config_found": True,
            "config_path": path,
            "error": "YAML parse failed",
            "error_type": exc.__class__.__name__,
            "config_version": None,
            "main_model": {"provider": "", "model": "", "base_url": ""},
            "auxiliary_models": {},
            "delegation": {"provider": "", "model": "", "display": "inherit main model"},
            "runtime_related": {"toolsets": [], "platform_toolsets": [], "approvals_mode": "", "compression_enabled": False, "memory_enabled": False, "curator_enabled": False, "timezone": ""},
            "docker_volumes": [],
            "warnings": [],
        }


def main():
    profile = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(summarize_config(profile=profile), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
