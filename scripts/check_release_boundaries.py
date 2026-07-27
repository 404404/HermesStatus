#!/usr/bin/env python3
"""Enforce frontend, protocol, and repository secret boundaries."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def repository_files() -> list[Path]:
    """Return tracked and untracked files, as they would exist after a commit."""
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        text=True,
    )
    return [
        ROOT / name
        for name in output.split("\0")
        if name and "__pycache__" not in Path(name).parts
    ]


PLACEHOLDER = re.compile(
    r"^(?:<[^>]+>|\$\{[^}]+\}|\{\{[^}]+\}\}|(?:ci[-_])?placeholder|example(?:[-_].*)?|"
    r"dummy(?:[-_].*)?|sample(?:[-_].*)?|test(?:[-_].*)?|fixture(?:[-_].*)?|"
    r"redacted|masked|hidden(?:[-_].*)?|changeme|replace[-_]?me|your[-_].*|user_default_password|"
    r"must[-_]?not[-_]?.*|do[-_]?not[-_]?.*|private[-_]?value|extremely[-_]?sensitive[-_]?value|"
    r"(?:model|nested|auxiliary)[-_]secret[-_]value|private[-_]log[-_]value|"
    r"not[-_]?a[-_]?real[-_]?.*|请替换.*)$",
    re.I,
)


def is_placeholder(value: str) -> bool:
    raw_value = value.strip()
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*\(", raw_value):
        return True
    value = raw_value.strip("'\"`.,;()[]")
    return (
        not value
        or value.startswith(("$", "{{"))
        or bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", value))
        or bool(PLACEHOLDER.fullmatch(value))
    )


SECRET_PATTERNS = {
    "private/SSH key": re.compile(
        r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----"
    ),
    "GitHub token": re.compile(
        r"\b(?:gh[oprsu]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"
    ),
    "OpenAI-style key": re.compile(
        r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"
    ),
    "API key": re.compile(
        r"(?i)\b(?:api[-_ ]?key|access[-_ ]?key|client[-_ ]?secret)\b\s*[:=]\s*['\"]?([^\s'\"#,}]{8,})"
    ),
    "Bearer token": re.compile(
        r"(?i)\b(?:authorization\s*[:=]\s*)?bearer\s+([A-Za-z0-9._~+/=-]{12,})"
    ),
    "password": re.compile(
        r"(?i)\b(?:password|passwd|pwd)\b\s*[:=]\s*['\"]?([^\s'\"#,}]{8,})"
    ),
    "Hermes token": re.compile(
        r"(?i)\b(?:hermes[-_ ]?(?:token|key)|admin[-_ ]?token)\b\s*[:=]\s*['\"]?([^\s'\"#,}]{8,})"
    ),
}


def secret_findings(content: str) -> list[str]:
    findings: list[str] = []
    for label, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(content):
            value = match.group(1) if match.lastindex else match.group(0)
            if not is_placeholder(value):
                findings.append(label)
                break
    return findings


def forbidden_environment_file(name: str) -> bool:
    basename = Path(name).name.lower()
    if basename == ".env":
        return True
    if not basename.startswith(".env."):
        return False
    return not basename.endswith((".example", ".sample", ".template"))


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def main() -> int:
    errors: list[str] = []
    files = repository_files()
    tracked_names = {path.relative_to(ROOT).as_posix() for path in files}

    for name in sorted(tracked_names):
        if forbidden_environment_file(name):
            fail(errors, f"tracked environment file is forbidden: {name}")
        if re.search(r"(^|/)(id_(rsa|dsa|ecdsa|ed25519)|.*\.pem|.*\.key)$", name, re.I):
            fail(errors, f"possible private key file is tracked: {name}")

    text_suffixes = {".go", ".py", ".js", ".html", ".css", ".json", ".yml", ".yaml", ".md", ".sh", ".service"}
    for path in files:
        if path.suffix.lower() not in text_suffixes and path.name not in {"Dockerfile", "Dockerfile.server", "Dockerfile.client"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(ROOT)
        for label in secret_findings(content):
            fail(errors, f"{relative}: possible {label}")

    frontend = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "web").rglob("*")
        if path.is_file() and path.suffix in {".html", ".js"}
    )
    required = {
        "主页 tab": r">主页</button>",
        "Docker tab": r">Docker</button>",
        "Lucky tab": r"id=[\"']luckyTab[\"']",
        "Lucky page": r"id=[\"']luckyPage[\"']",
        "stats endpoint": r"/json/stats\.json",
        "10-minute refresh": r"10\s*\*\s*60\s*\*\s*1000",
    }
    forbidden = {
        "Docker command rendering": r"docker[^\n]{0,30}command|command[^\n]{0,30}docker",
        "legacy Docker endpoint": r"/api/docker",
        "browser Hermes API": r"fetch\s*\([^)]*/api/(?:hermes|profiles)",
        "browser Lucky API": r"/(?:api/(?:info|status|netinterfaces|ddnstasklist|webservice|portforwards|ssl)|version)",
        "browser Lucky credential": r"Lucky-Admin-Token|openToken|LUCKY_TOKEN|127\.0\.0\.1:16601",
        "WebSocket": r"new\s+WebSocket\s*\(",
        "EventSource/SSE": r"new\s+EventSource\s*\(",
    }
    for label, pattern in required.items():
        if not re.search(pattern, frontend, re.I):
            fail(errors, f"frontend invariant missing: {label}")
    for label, pattern in forbidden.items():
        if re.search(pattern, frontend, re.I):
            fail(errors, f"frontend invariant violated: {label}")
    if len(re.findall(r"setInterval\s*\(", (ROOT / "web/js/app.js").read_text())) > 1:
        fail(errors, "frontend creates more than one interval call site")

    server_runtime = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "server").glob("*.go")
        if path.is_file() and not path.name.endswith("_test.go")
    )
    if re.search(r"Lucky-Admin-Token|openToken|LUCKY_TOKEN|lucky_json", server_runtime):
        fail(errors, "server runtime must not receive Lucky credentials or a Legacy lucky_json field")

    if errors:
        print("Release boundary validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Release boundary and secret checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
