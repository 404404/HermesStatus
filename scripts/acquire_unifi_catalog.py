#!/usr/bin/env python3
"""Acquire and stage the exact locked UniFi_Catalog build artifact.

The source repository is supplied by CI as a separately checked-out directory.
This helper never clones, fetches, or otherwise performs network I/O. It fails
closed unless the checkout, external validation, deterministic build, and
resulting bundle all match the repository lock file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


LOCK_KEYS = {"repository", "revision", "schema_version", "catalog_sha256"}
HEX = set("0123456789abcdef")
ARTIFACTS = ("catalog.json", "catalog.sha256", "manifest.json")


class CatalogAcquisitionError(ValueError):
    """Raised when a locked external Catalog cannot be trusted."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogAcquisitionError(f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise CatalogAcquisitionError(f"invalid {label}")
    return value


def load_lock(path: Path) -> dict[str, Any]:
    lock = _read_json(path, "Catalog lock")
    if set(lock) != LOCK_KEYS:
        raise CatalogAcquisitionError("Catalog lock keys are not exact")
    repository = lock["repository"]
    revision = lock["revision"]
    schema_version = lock["schema_version"]
    digest = lock["catalog_sha256"]
    if repository != "404404/UniFi_Catalog":
        raise CatalogAcquisitionError("Catalog repository is not the approved source")
    if not isinstance(revision, str) or len(revision) != 40 or any(char not in HEX for char in revision):
        raise CatalogAcquisitionError("Catalog revision must be a full lowercase Git SHA")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != 1:
        raise CatalogAcquisitionError("unsupported Catalog schema version")
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in HEX for char in digest):
        raise CatalogAcquisitionError("Catalog SHA-256 must be a lowercase hexadecimal digest")
    return lock


def _git_output(source_dir: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source_dir), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CatalogAcquisitionError("unable to inspect external Catalog checkout") from exc
    return result.stdout.strip()


def verify_checkout(source_dir: Path, lock: dict[str, Any]) -> None:
    if not source_dir.is_dir():
        raise CatalogAcquisitionError("external Catalog checkout is missing")
    head = _git_output(source_dir, "rev-parse", "--verify", "HEAD^{commit}")
    if head != lock["revision"]:
        raise CatalogAcquisitionError("external Catalog checkout revision does not match lock")
    if _git_output(source_dir, "status", "--porcelain"):
        raise CatalogAcquisitionError("external Catalog checkout is dirty")
    for relative in ("tools/validate_catalog.py", "tools/build_catalog.py", "tests"):
        if not (source_dir / relative).exists():
            raise CatalogAcquisitionError(f"external Catalog checkout is missing {relative}")


def run_external(source_dir: Path, arguments: list[str]) -> None:
    command = [sys.executable, *arguments]
    try:
        subprocess.run(command, cwd=source_dir, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CatalogAcquisitionError("external Catalog validation/build failed") from exc


def _artifact_bytes(directory: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for name in ARTIFACTS:
        try:
            result[name] = (directory / name).read_bytes()
        except OSError as exc:
            raise CatalogAcquisitionError(f"Catalog build did not produce {name}") from exc
    return result


def _verify_build(directory: Path, lock: dict[str, Any]) -> dict[str, bytes]:
    artifacts = _artifact_bytes(directory)
    try:
        bundle = json.loads(artifacts["catalog.json"].decode("utf-8"))
        digest_line = artifacts["catalog.sha256"].decode("ascii").strip()
        manifest = json.loads(artifacts["manifest.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogAcquisitionError("Catalog build output is not valid JSON/ASCII") from exc
    if not isinstance(bundle, dict) or bundle.get("schema_version") != lock["schema_version"]:
        raise CatalogAcquisitionError("Catalog bundle schema version does not match lock")
    if not isinstance(manifest, dict):
        raise CatalogAcquisitionError("Catalog build manifest is invalid")
    if digest_line != f"{lock['catalog_sha256']}  catalog.json":
        raise CatalogAcquisitionError("Catalog build digest manifest does not match lock")
    if hashlib.sha256(artifacts["catalog.json"]).hexdigest() != lock["catalog_sha256"]:
        raise CatalogAcquisitionError("Catalog bundle SHA-256 does not match lock")
    expected_manifest = {
        "bundle_sha256": lock["catalog_sha256"],
        "catalog_schema_version": lock["schema_version"],
        "model_count": manifest.get("model_count"),
    }
    if manifest != expected_manifest or not isinstance(manifest["model_count"], int) or manifest["model_count"] <= 0:
        raise CatalogAcquisitionError("Catalog build manifest is invalid")
    return artifacts


def _provenance_bytes(lock: dict[str, Any]) -> bytes:
    return (json.dumps(
        {
            "catalog_sha256": lock["catalog_sha256"],
            "catalog_schema_version": lock["schema_version"],
            "repository": lock["repository"],
            "revision": lock["revision"],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n").encode("utf-8")


def acquire(source_dir: Path, output_dir: Path, lock_path: Path) -> dict[str, Any]:
    lock = load_lock(lock_path)
    verify_checkout(source_dir, lock)
    with tempfile.TemporaryDirectory(prefix="hermesstatus-catalog-build-") as temporary:
        temporary_path = Path(temporary)
        first = temporary_path / "one"
        second = temporary_path / "two"
        run_external(source_dir, ["tools/validate_catalog.py", "--root", str(source_dir), "--check-generated"])
        run_external(source_dir, ["-m", "unittest", "discover", "-s", "tests", "-v"])
        run_external(source_dir, ["tools/build_catalog.py", "--root", str(source_dir), "--check", "--output-dir", str(first)])
        run_external(source_dir, ["tools/build_catalog.py", "--root", str(source_dir), "--check", "--output-dir", str(second)])
        first_artifacts = _verify_build(first, lock)
        second_artifacts = _verify_build(second, lock)
        if first_artifacts != second_artifacts:
            raise CatalogAcquisitionError("Catalog deterministic builds differ")

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in first_artifacts.items():
        target = output_dir / name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise CatalogAcquisitionError(f"unsafe Catalog staging target: {name}")
        target.write_bytes(content)
    provenance_path = output_dir / "catalog-provenance.json"
    if provenance_path.is_symlink() or (provenance_path.exists() and not provenance_path.is_file()):
        raise CatalogAcquisitionError("unsafe Catalog staging target: catalog-provenance.json")
    provenance_path.write_bytes(_provenance_bytes(lock))
    return lock


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path, default=Path(__file__).resolve().parents[1] / "unifi-catalog.lock.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        lock = acquire(args.source_dir.resolve(), args.output_dir.resolve(), args.lock_file.resolve())
    except (CatalogAcquisitionError, OSError) as exc:
        print(f"CATALOG_ACQUISITION=FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "CATALOG_ACQUISITION=PASS "
        f"revision={lock['revision']} schema_version={lock['schema_version']} "
        f"catalog_sha256={lock['catalog_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
