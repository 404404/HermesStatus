#!/usr/bin/env python3
import importlib.util
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "hermes_config_summary.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_config_summary", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_config(directory, text):
    path = pathlib.Path(directory) / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def summary_for(text):
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        path = write_config(tmp, text)
        return module.summarize_config(env={"HERMES_CONFIG_PATH": str(path), "HOME": tmp})


def test_normal_config():
    data = summary_for("""
_config_version: 23
model:
  provider: openai-codex
  default: gpt-5.5
  base_url: https://chatgpt.com/backend-api/codex
auxiliary:
  web_extract:
    provider: auto
    model: ""
    base_url: ""
    timeout: 360
    download_timeout: 30
    language: ""
toolsets: [hermes-cli]
platform_toolsets: [docker]
terminal:
  docker_volumes:
    - /home/hermes/workspaces/hermes3:/workspace
    - /etc/localtime:/etc/localtime:ro
approvals:
  mode: manual
compression:
  enabled: true
memory:
  memory_enabled: true
curator:
  enabled: true
timezone: Asia/Shanghai
""")
    assert data["config_found"] is True
    assert data["config_version"] == 23
    assert data["main_model"]["model"] == "gpt-5.5"
    assert data["main_model"]["provider"] == "openai-codex"
    assert data["auxiliary_models"]["web_extract"]["display"] == "openai-codex / gpt-5.5"
    assert data["auxiliary_models"]["web_extract"]["source"] == "main_model"
    assert data["auxiliary_models"]["web_extract"]["download_timeout_seconds"] == 30
    assert data["auxiliary_models"]["web_extract"]["language"] == ""
    assert data["docker_volumes"] == ["/home/hermes/workspaces/hermes3:/workspace", "/etc/localtime:/etc/localtime:ro"]
    assert data["runtime_related"]["approvals_mode"] == "manual"
    assert data["runtime_related"]["compression_enabled"] is True


def test_missing_auxiliary():
    data = summary_for("""
model:
  provider: openai-codex
  model: gpt-5.5
""")
    assert data["auxiliary_models"] == {}
    assert data["delegation"]["display"] == "inherit main model"


def test_profile_config_path_prefers_dot_hermes_profiles():
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        preferred = root / ".hermes" / "profiles" / "hermes1"
        legacy = root / "hermes1"
        preferred.mkdir(parents=True)
        legacy.mkdir(parents=True)
        write_config(legacy, """
model:
  provider: legacy
  model: old
""")
        write_config(preferred, """
model:
  provider: openai-codex
  default: gpt-5.5
""")
        data = module.summarize_config(env={"HOME": tmp}, hermes_root=tmp, profile="hermes1", profile_dir=str(legacy))
    assert data["config_path"].endswith("/.hermes/profiles/hermes1/config.yaml")
    assert data["main_model"]["provider"] == "openai-codex"


def test_explicit_config_path_wins():
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        explicit_dir = root / "custom"
        profile_dir = root / "hermes1"
        explicit_dir.mkdir()
        profile_dir.mkdir()
        explicit_path = write_config(explicit_dir, """
model:
  provider: explicit
  model: configured
""")
        write_config(profile_dir, """
model:
  provider: legacy
  model: old
""")
        data = module.summarize_config(
            env={"HOME": tmp},
            hermes_root=tmp,
            profile="hermes1",
            profile_dir=str(profile_dir),
            config_path=str(explicit_path),
        )
    assert data["config_path"] == str(explicit_path)
    assert data["main_model"]["provider"] == "explicit"


def test_missing_delegation():
    data = summary_for("""
model:
  provider: openai-codex
  default: gpt-5.5
auxiliary:
  vision:
    provider: auto
    model: ""
""")
    assert data["delegation"]["provider"] == ""
    assert data["delegation"]["model"] == ""
    assert data["delegation"]["display"] == "inherit main model"


def test_auto_provider_empty_model():
    data = summary_for("""
model:
  provider: openai-codex
  default: gpt-5.5
  base_url: https://chatgpt.com/backend-api/codex
auxiliary:
  vision:
    provider: auto
    model: ""
  session_search:
    provider: custom
    model: should-not-display
""")
    assert data["auxiliary_models"]["vision"]["display"] == "openai-codex / gpt-5.5"
    assert data["auxiliary_models"]["vision"]["source"] == "main_model"
    assert data["auxiliary_models"]["vision"]["base_url_display"] == "https://chatgpt.com/backend-api/codex"
    assert "session_search" not in data["auxiliary_models"]


def test_provider_default_model():
    data = summary_for("""
auxiliary:
  web_extract:
    provider: openai-codex
    model: ""
""")
    assert data["auxiliary_models"]["web_extract"]["display"] == "openai-codex / default"
    assert data["auxiliary_models"]["web_extract"]["base_url_display"] == "provider default"


def test_configured_auxiliary_uses_own_model():
    data = summary_for("""
model:
  provider: openai-codex
  default: gpt-5.5
  base_url: https://chatgpt.com/backend-api/codex
auxiliary:
  vision:
    provider: gemini
    model: gemini-3.1-flash-lite
    base_url: https://generativelanguage.googleapis.com
""")
    assert data["auxiliary_models"]["vision"]["display"] == "gemini / gemini-3.1-flash-lite"
    assert data["auxiliary_models"]["vision"]["source"] == "config"
    assert data["auxiliary_models"]["vision"]["base_url_display"] == "https://generativelanguage.googleapis.com"


def test_sensitive_fields_are_redacted():
    data = summary_for("""
model:
  provider: openai-codex
  model: gpt-5.5
  api_key: sk-secret-model
auxiliary:
  curator:
    provider: google-ai-studio
    model: gemini-2.5-flash
    token: token-secret
    extra_body:
      api_key: nested-secret
""")
    payload = str(data)
    assert "sk-secret-model" not in payload
    assert "token-secret" not in payload
    assert "nested-secret" not in payload
    assert data["main_model"]["api_key_configured"] is True
    assert data["main_model"]["api_key_source"] == "config"
    assert data["auxiliary_models"]["curator"]["token_configured"] is True
    assert data["auxiliary_models"]["curator"]["token_source"] == "config"
    assert data["auxiliary_models"]["curator"]["extra_body_configured"] is True


def test_yaml_parse_error():
    data = summary_for("""
model: [unterminated
""")
    assert data["config_found"] is True
    assert isinstance(data, dict)
    assert "unterminated" not in str(data)


def test_missing_config_includes_checked_paths():
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        data = module.summarize_config(env={"HOME": tmp}, hermes_root=tmp, profile="hermes1")
    assert data["config_found"] is False
    assert data["error"] == "Hermes config.yaml not found"
    assert data["checked_paths"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("hermes config summary checks passed")
