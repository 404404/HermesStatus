#!/usr/bin/env python3
"""Reject reintroduction of local UniFi static-model authority."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIRECTORY = ROOT / "clients" / "unifi_profiles"
PROFILE_STATIC_KEYS = {"fans", "power", "storage", "cpu_model", "poe"}
def production_files() -> tuple[Path, ...]:
    client_files = [
        path for path in (ROOT / "clients").glob("*.py")
        if not path.name.startswith("test_") and path.name != "unifi_model_catalog.py"
    ]
    frontend_files = [
        path for path in (ROOT / "web").rglob("*.js")
        if not path.name.endswith(".test.js")
    ]
    return tuple(sorted(client_files + frontend_files))
LEGACY_PATTERNS = (
    ("profile-to-SKU mapping", re.compile(r"MODEL_SKU_BY_PROFILE")),
    ("profile fan authority", re.compile(r"profile\s*(?:\[\s*['\"]fans['\"]\s*\]|\.get\(\s*['\"]fans['\"]\s*\))")),
    ("profile power authority", re.compile(r"profile\s*(?:\[\s*['\"]power['\"]\s*\]|\.get\(\s*['\"]power['\"]\s*\))")),
    ("profile storage authority", re.compile(r"profile\s*(?:\[\s*['\"]storage['\"]\s*\]|\.get\(\s*['\"]storage['\"]\s*\))")),
    ("profile CPU authority", re.compile(r"profile\s*(?:\[\s*['\"]cpu_model['\"]\s*\]|\.get\(\s*['\"]cpu_model['\"]\s*\))")),
    ("profile PoE authority", re.compile(r"profile\s*(?:\[\s*['\"]poe['\"]\s*\]|\.get\(\s*['\"]poe['\"]\s*\))")),
    ("model-to-static local table", re.compile(
        r"['\"](?:udw|ucg[- ]max|ucg max|unifi dream wall)['\"]\s*:\s*\{[^{}]{0,512}"
        r"(?:ports|poe|storage|psu|cpu_model|fans)\b",
        re.IGNORECASE | re.DOTALL,
    )),
)


def _profile_source_count(value) -> int:
    if isinstance(value, dict):
        count = 1 if isinstance(value.get("source"), str) else 0
        return count + sum(_profile_source_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(_profile_source_count(item) for item in value)
    return 0


def collector_configuration_occurrences() -> int:
    total = 0
    for path in sorted(PROFILE_DIRECTORY.glob("*.json")):
        if path.name == "profile.schema.json":
            continue
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        total += _profile_source_count(profile)
    return total


def findings() -> list[str]:
    result: list[str] = []
    for path in sorted(PROFILE_DIRECTORY.glob("*.json")):
        if path.name == "profile.schema.json":
            continue
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            result.append(f"{path.relative_to(ROOT)}: unreadable profile: {exc}")
            continue
        for key in sorted(PROFILE_STATIC_KEYS & set(profile)):
            result.append(f"{path.relative_to(ROOT)}: forbidden static profile field {key!r}")

    for path in production_files():
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            result.append(f"{path.relative_to(ROOT)}: unreadable production file: {exc}")
            continue
        for label, pattern in LEGACY_PATTERNS:
            if pattern.search(content):
                result.append(f"{path.relative_to(ROOT)}: forbidden {label}")
    return result


def main() -> int:
    errors = findings()
    print(f"STATIC_MODEL_TRUTH_OCCURRENCES={len(errors)}")
    print(f"COLLECTOR_CONFIGURATION_OCCURRENCES={collector_configuration_occurrences()}")
    if errors:
        print("UniFi Catalog authority guard failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("UniFi Catalog authority guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
