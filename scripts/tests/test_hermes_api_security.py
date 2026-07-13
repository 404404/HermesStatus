#!/usr/bin/env python3
import importlib.util
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "scripts" / "export-hermes-status.py"


def load_exporter():
    spec = importlib.util.spec_from_file_location("export_hermes_status", EXPORTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reset_env(module, root):
    module.HERMES_ROOT = Path(root)
    module.PROFILE_ENV_CACHE.clear()
    for key in list(os.environ):
        if key.startswith("HERMES_API_") or key.startswith("API_SERVER_") or key.endswith("_API_SERVER_KEY"):
            os.environ.pop(key, None)


def write_profile(root, profile, text):
    path = Path(root) / profile
    path.mkdir(parents=True, exist_ok=True)
    (path / ".env").write_text(text, encoding="utf-8")


def main():
    module = load_exporter()
    with tempfile.TemporaryDirectory() as tmp:
        reset_env(module, tmp)
        write_profile(tmp, "hermes1", "")
        assert module.api_base_url("hermes1") == ""

        reset_env(module, tmp)
        write_profile(tmp, "hermes1", "API_SERVER_ENABLED=false\nAPI_SERVER_PORT=8642\nAPI_SERVER_KEY=secret\n")
        assert module.api_base_url("hermes1") == ""

        reset_env(module, tmp)
        write_profile(tmp, "hermes1", "API_SERVER_PORT=8642\nAPI_SERVER_KEY=secret\n")
        assert module.api_base_url("hermes1") == "http://127.0.0.1:8642"

        reset_env(module, tmp)
        write_profile(tmp, "hermes1", "API_SERVER_ENABLED=true\nAPI_SERVER_HOST=0.0.0.0\nAPI_SERVER_PORT=8642\n")
        assert module.api_base_url("hermes1") == "http://127.0.0.1:8642"
        data, err = module.http_json("hermes1", "/health")
        assert data is None
        assert err == "missing API_SERVER_KEY"

        reset_env(module, tmp)
        write_profile(tmp, "hermes3", "API_SERVER_ENABLED=true\nAPI_SERVER_PORT=8644\nAPI_SERVER_KEY=from-profile\n")
        assert module.api_base_url("hermes3") == "http://127.0.0.1:8644"
        assert module.api_token("hermes3") == "from-profile"

        reset_env(module, tmp)
        write_profile(tmp, "hermes2", "API_SERVER_ENABLED=true\nAPI_SERVER_PORT=8643\n")
        os.environ["API_SERVER_KEY_HERMES2"] = "from-env"
        assert module.api_token("hermes2") == "from-env"

        def fake_http_json(profile, path, method="GET", payload=None):
            if path == "/health":
                return {"status": "ok"}, ""
            if path == "/health/detailed":
                return {"status": "ok"}, ""
            if path == "/api/jobs":
                return {"jobs": []}, ""
            if path == "/api/sessions?limit=100&offset=0":
                return {
                    "has_more": True,
                    "limit": 2,
                    "offset": 0,
                    "data": [
                        {"id": "s1", "input_tokens": 10, "output_tokens": 2},
                        {"id": "s2", "usage": {"prompt_tokens": 7, "completion_tokens": 3}},
                    ]
                }, ""
            if path == "/api/sessions?limit=100&offset=2":
                return {
                    "has_more": False,
                    "limit": 2,
                    "offset": 2,
                    "data": [
                        {"id": "s3", "input_tokens": 1, "output_tokens": 1},
                    ]
                }, ""
            if path == "/api/sessions":
                return {"has_more": False, "data": []}, ""
            if path == "/v1/toolsets":
                return {"data": [{
                    "name": "moa",
                    "label": "Mixture of Agents",
                    "description": "Multi-model consensus",
                    "enabled": True,
                    "configured": False,
                    "tools": ["mixture_of_agents"],
                }]}, ""
            if path.startswith("/v1/"):
                return {}, ""
            return None, "unexpected"

        old_http_json = module.http_json
        try:
            module.http_json = fake_http_json
            api = module.collect_api("hermes1")
            assert api["usage"] == {"input_tokens": 18, "output_tokens": 6, "total_tokens": 24}
            assert api["sessions_total_count"] == 3
            assert api["sessions_has_more"] is False
            assert api["sessions"][0]["usage"] == {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
            assert api["mixture_of_agents"] == {
                "source": "GET /v1/toolsets",
                "available": True,
                "name": "moa",
                "label": "Mixture of Agents",
                "description": "Multi-model consensus",
                "enabled": True,
                "configured": False,
                "tools": ["mixture_of_agents"],
            }
        finally:
            module.http_json = old_http_json

        by_tool = module.mixture_of_agents_from_toolsets([
            {"name": "reasoning", "tools": ["mixture_of_agents"]}
        ])
        assert by_tool["available"] is True
        assert by_tool["name"] == "reasoning"

        missing = module.mixture_of_agents_from_toolsets({"data": []})
        assert missing["available"] is False
        assert missing["source"] == "GET /v1/toolsets"

        old_run_text = module.run_text
        old_run_host_text = module.run_host_text
        try:
            module.HERMES_VERSION_CACHE = None
            module.run_text = lambda cmd: "\x1b[32mHermes Agent 0.3.0\x1b[0m\n" if cmd == ["hermes", "--version"] else ""
            module.run_host_text = lambda command: ""
            assert module.hermes_agent_version() == "0.3.0"
        finally:
            module.run_text = old_run_text
            module.run_host_text = old_run_host_text
            module.HERMES_VERSION_CACHE = None

    print("hermes api security checks passed")


if __name__ == "__main__":
    main()
