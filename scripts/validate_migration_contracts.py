#!/usr/bin/env python3
"""Validate migration schemas and fixtures without third-party packages."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "docs" / "migration" / "schema"
FIXTURE_DIR = ROOT / "testdata" / "migration"
MIGRATION_DOC_DIR = ROOT / "docs" / "migration"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
SAFE_INTEGER_MAX = 9007199254740991


class ContractError(Exception):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"{path.relative_to(ROOT)}: invalid JSON: {exc}") from exc


SCHEMAS = {path.resolve(): load_json(path) for path in sorted(SCHEMA_DIR.glob("*.json"))}


def pointer_get(document: Any, pointer: str) -> Any:
    if not pointer:
        return document
    if not pointer.startswith("/"):
        raise ContractError(f"unsupported JSON pointer: {pointer}")
    value = document
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            value = value[int(token)]
        else:
            value = value[token]
    return value


def resolve_ref(ref: str, current_path: Path) -> tuple[Any, Path]:
    base, _, fragment = ref.partition("#")
    target_path = (current_path.parent / base).resolve() if base else current_path.resolve()
    if target_path not in SCHEMAS:
        raise ContractError(f"unresolved schema reference {ref!r} from {current_path.name}")
    return pointer_get(SCHEMAS[target_path], fragment), target_path


def type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise ContractError(f"validator does not implement JSON Schema type {expected!r}")


def validate(value: Any, schema: Any, schema_path: Path, path: str = "$") -> None:
    if schema is True:
        return
    if schema is False:
        raise ContractError(f"{path}: rejected by false schema")
    if "$ref" in schema:
        target, target_path = resolve_ref(schema["$ref"], schema_path)
        validate(value, target, target_path, path)
        return
    if "allOf" in schema:
        for item in schema["allOf"]:
            validate(value, item, schema_path, path)
    if "anyOf" in schema:
        errors = []
        for item in schema["anyOf"]:
            try:
                validate(value, item, schema_path, path)
                break
            except ContractError as exc:
                errors.append(str(exc))
        else:
            raise ContractError(f"{path}: no anyOf branch matched: {'; '.join(errors)}")
    if "const" in schema and value != schema["const"]:
        raise ContractError(f"{path}: expected constant {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"{path}: value {value!r} is not in enum {schema['enum']!r}")

    expected = schema.get("type")
    if expected is not None:
        types = [expected] if isinstance(expected, str) else expected
        if not any(type_matches(value, item) for item in types):
            raise ContractError(f"{path}: expected type {types!r}, got {type(value).__name__}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise ContractError(f"{path}: missing required properties {missing!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ContractError(f"{path}: additional properties are forbidden: {unknown!r}")
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], schema_path, f"{path}.{key}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise ContractError(f"{path}: has {len(value)} items, below minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ContractError(f"{path}: has {len(value)} items, above maxItems {schema['maxItems']}")
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            raise ContractError(f"{path}: duplicate items are forbidden")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                validate(item, item_schema, schema_path, f"{path}[{index}]")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ContractError(f"{path}: string length {len(value)} is below {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ContractError(f"{path}: string length {len(value)} exceeds {schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ContractError(f"{path}: string does not match {schema['pattern']!r}")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ContractError(f"{path}: invalid RFC 3339 date-time {value!r}") from exc
            if parsed.tzinfo is None:
                raise ContractError(f"{path}: date-time must include a timezone")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ContractError(f"{path}: value {value} is below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ContractError(f"{path}: value {value} exceeds maximum {schema['maximum']}")


def validate_semantics(data: dict[str, Any], fixture: Path) -> None:
    prefix = fixture.relative_to(ROOT)
    for domain_name in ("hardware", "docker", "hermes"):
        domain = data[domain_name]
        if domain["updated_at"] is None and domain["stale"] is not True:
            raise ContractError(f"{prefix}: {domain_name}.updated_at null requires stale=true")

    docker = data["docker"]
    if docker["running"] > docker["total"]:
        raise ContractError(f"{prefix}: docker.running exceeds docker.total")
    if not docker["truncated"] and len(docker["containers"]) != docker["total"]:
        raise ContractError(f"{prefix}: untruncated docker list length must equal total")
    if docker["truncated"] and len(docker["containers"]) >= docker["total"]:
        raise ContractError(f"{prefix}: truncated docker list must be shorter than total")

    for index, profile in enumerate(data["hermes"]["profiles"]):
        if profile["updated_at"] is None and profile["stale"] is not True:
            raise ContractError(f"{prefix}: profile[{index}] null updated_at requires stale=true")
        usage = profile["usage"]
        counts = [usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]]
        if all(item is not None for item in counts) and counts[0] + counts[1] != counts[2]:
            raise ContractError(f"{prefix}: profile[{index}] total_tokens is not input+output")
        if (usage["window_start"] is None) != (usage["window_end"] is None):
            raise ContractError(f"{prefix}: profile[{index}] token windows must both be null or set")
        if usage["source"] == "unavailable":
            if any(item is not None for item in counts) or usage["window_start"] is not None or not usage["estimated"]:
                raise ContractError(f"{prefix}: unavailable usage must be null and estimated")
        if usage["source"] in {"local_session_state", "local_logs"} and not usage["estimated"]:
            raise ContractError(f"{prefix}: local usage source must be estimated")


FORBIDDEN_KEYS = {
    "api_key",
    "api_server_key",
    "password",
    "authorization",
    "authorization_header",
    "access_token",
    "refresh_token",
    "token_secret",
    "env_raw",
    "config_yaml_raw",
}
SUSPICIOUS_VALUES = [
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\b(api[_ -]?key|password|authorization)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\btoken\s*[:=]\s*[A-Za-z0-9._-]{8,}", re.IGNORECASE),
    re.compile(r"\b10(?:\.\d{1,3}){3}\b"),
    re.compile(r"\b192\.168(?:\.\d{1,3}){2}\b"),
    re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}\b"),
]


def scan_secrets(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                raise ContractError(f"{path}: forbidden secret-bearing key {key!r}")
            scan_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            scan_secrets(item, f"{path}[{index}]")
    elif isinstance(value, str):
        for pattern in SUSPICIOUS_VALUES:
            if pattern.search(value):
                raise ContractError(f"{path}: suspicious secret or private address pattern {pattern.pattern!r}")


def github_heading_slug(heading: str) -> str:
    heading = re.sub(r"`([^`]*)`", r"\1", heading.strip().lower())
    heading = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", heading)
    chars = []
    for char in heading:
        category = unicodedata.category(char)
        if category.startswith(("L", "N")) or char in {"_", "-", " "}:
            chars.append(char)
    return re.sub(r"\s+", "-", "".join(chars))


def markdown_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        base = github_heading_slug(match.group(1))
        count = counts.get(base, 0)
        counts[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


def validate_markdown_links() -> int:
    markdown_files = sorted(MIGRATION_DOC_DIR.glob("*.md"))
    anchor_cache = {path.resolve(): markdown_anchors(path) for path in markdown_files}
    checked = 0
    link_pattern = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
    for source in markdown_files:
        in_fence = False
        for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for raw_target in link_pattern.findall(line):
                target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path_part, _, fragment = target.partition("#")
                resolved = (source.parent / unquote(path_part)).resolve() if path_part else source.resolve()
                if not resolved.exists():
                    raise ContractError(
                        f"{source.relative_to(ROOT)}:{line_number}: missing Markdown target {target!r}"
                    )
                if fragment and resolved.suffix.lower() == ".md":
                    anchors = anchor_cache.get(resolved)
                    if anchors is None:
                        anchors = markdown_anchors(resolved)
                        anchor_cache[resolved] = anchors
                    decoded_fragment = unquote(fragment).lower()
                    if decoded_fragment not in anchors:
                        raise ContractError(
                            f"{source.relative_to(ROOT)}:{line_number}: missing Markdown anchor {target!r}"
                        )
                checked += 1
    return checked


def validate_fixture_coverage(fixtures: dict[str, dict[str, Any]]) -> None:
    expected = {
        "update-normal.json", "update-empty.json", "update-degraded.json", "update-long-values.json",
        "stats-normal.json", "stats-empty.json", "stats-degraded.json", "stats-long-values.json",
    }
    if set(fixtures) != expected:
        raise ContractError(f"fixture set mismatch: expected {sorted(expected)}, got {sorted(fixtures)}")

    for prefix in ("update", "stats"):
        normal = fixtures[f"{prefix}-normal.json"]
        if not normal["docker"]["containers"] or not normal["hermes"]["profiles"]:
            raise ContractError(f"{prefix}-normal.json must cover non-empty Docker and Hermes data")
        empty = fixtures[f"{prefix}-empty.json"]
        if empty["docker"]["containers"] or empty["hermes"]["profiles"] or empty["hardware"]["cpu_temperature"] is not None:
            raise ContractError(f"{prefix}-empty.json does not cover required empty cases")
        degraded = fixtures[f"{prefix}-degraded.json"]
        codes = {
            degraded["hardware"]["error"]["code"],
            degraded["docker"]["error"]["code"],
            *(item["error"]["code"] for item in degraded["hermes"]["profiles"]),
        }
        required_codes = {"smartctl_unavailable", "docker_unavailable", "api_unauthorized", "api_timeout"}
        if not required_codes.issubset(codes):
            raise ContractError(f"{prefix}-degraded.json is missing degraded cases {sorted(required_codes - codes)}")
        long_data = fixtures[f"{prefix}-long-values.json"]
        container = long_data["docker"]["containers"][0]
        profile = long_data["hermes"]["profiles"][0]
        volume = profile["config_summary"]["docker_volumes"][0]
        if len(container["image"]) < 160 or len(container["status"]) < 100 or len(profile["model"]) < 180 or len(volume) < 350:
            raise ContractError(f"{prefix}-long-values.json does not exercise all long-value boundaries")


def main() -> int:
    checked_links = validate_markdown_links()
    for path, schema in SCHEMAS.items():
        if schema.get("$schema") != DRAFT_2020_12:
            raise ContractError(f"{path.relative_to(ROOT)}: schema is not Draft 2020-12")
        scan_secrets(schema.get("examples", []), f"{path.name}.examples")
        for index, example in enumerate(schema.get("examples", [])):
            validate(example, schema, path, f"{path.name}.examples[{index}]")

    fixtures = {path.name: load_json(path) for path in sorted(FIXTURE_DIR.glob("*.json"))}
    validate_fixture_coverage(fixtures)
    for name, data in fixtures.items():
        schema_name = "agent-update-extension.schema.json" if name.startswith("update-") else "stats-extension.schema.json"
        schema_path = (SCHEMA_DIR / schema_name).resolve()
        validate(data, SCHEMAS[schema_path], schema_path)
        validate_semantics(data, FIXTURE_DIR / name)
        scan_secrets(data, name)
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 65536:
            raise ContractError(f"{name}: compact payload exceeds 65536 bytes")
        print(f"ok  {name:<30} {len(encoded):>5} bytes")

    print(
        f"validated {checked_links} Markdown links, {len(SCHEMAS)} schemas, "
        f"their examples, and {len(fixtures)} fixtures"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
