#!/usr/bin/env python3
import importlib.util
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "scripts" / "export-hermes-status.py"


def load_exporter(config_path):
    old_config = os.environ.get("HERMES_EXPORT_CONFIG")
    os.environ["HERMES_EXPORT_CONFIG"] = str(config_path)
    try:
        spec = importlib.util.spec_from_file_location("export_hermes_status_config_test", EXPORTER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if old_config is None:
            os.environ.pop("HERMES_EXPORT_CONFIG", None)
        else:
            os.environ["HERMES_EXPORT_CONFIG"] = old_config


def main():
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "hermes-exporter.json"
        config.write_text(json.dumps({
            "hermes_root": "/custom/hermes",
            "status_dir": "/custom/status",
            "profiles": [
                {
                    "name": "daily",
                    "profile_dir": "/custom/hermes/daily-profile",
                    "config_path": "/custom/hermes/.hermes/profiles/daily/config.yaml",
                    "env_path": "/custom/hermes/daily-profile/.env",
                    "api": {
                        "enabled": True,
                        "host": "127.0.0.1",
                        "port": 18642
                    }
                }
            ]
        }), encoding="utf-8")

        module = load_exporter(config)

    assert module.PROFILES == ["daily"]
    assert str(module.HERMES_ROOT) == "/custom/hermes"
    assert str(module.OUTPUT_DIR) == "/custom/status"
    assert str(module.profile_dir_for("daily")) == "/custom/hermes/daily-profile"
    assert module.profile_config_path_for("daily") == "/custom/hermes/.hermes/profiles/daily/config.yaml"
    assert module.api_base_url("daily") == "http://127.0.0.1:18642"

    print("hermes export config checks passed")


if __name__ == "__main__":
    main()
