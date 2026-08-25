#!/usr/bin/env python3
"""Validate immutable HermesStatus image identity without exposing build inputs."""

import argparse
import datetime as dt
import json
import re
import subprocess
import sys


REQUIRED_LABELS = (
    "org.opencontainers.image.title",
    "org.opencontainers.image.description",
    "org.opencontainers.image.version",
    "org.opencontainers.image.revision",
    "org.opencontainers.image.created",
    "org.opencontainers.image.source",
    "org.opencontainers.image.licenses",
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PRODUCT_VERSION_PATTERN = re.compile(r"^2\.3$")
CANDIDATE_TAG_PATTERN = re.compile(r"^(?P<version>2\.3)-(?P<revision>[0-9a-f]{12})$")
COMPONENT_LABEL = "io.hermesstatus.component"
SECRET_PATTERN = re.compile(
    r"(?i)(authorization\s*:|bearer\s+|api[_-]?key|password|private[_-]?key|token[_-]?secret)"
)


class ValidationError(ValueError):
    pass


def inspect_image(image: str) -> dict:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValidationError("docker inspect must return exactly one image")
    return payload[0]


def validate_created(value: str) -> None:
    if not value.endswith("Z"):
        raise ValidationError("created label must use UTC RFC3339 with a Z suffix")
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValidationError("created label is not UTC RFC3339") from exc



def validate_candidate_tag(candidate_tag: str, product_version: str, revision: str) -> None:
    if not PRODUCT_VERSION_PATTERN.fullmatch(product_version):
        raise ValidationError("product version must be the formal 2.3 release line")
    match = CANDIDATE_TAG_PATTERN.fullmatch(candidate_tag)
    if match is None:
        raise ValidationError("candidate tag must be 2.3- followed by a 12-character lowercase Git SHA")
    if match.group("version") != product_version or match.group("revision") != revision[:12]:
        raise ValidationError("candidate tag does not match the formal version and full revision")


def environment_values(config: dict) -> dict:
    values = {}
    for item in config.get("Env") or []:
        if not isinstance(item, str) or "=" not in item:
            continue
        key, value = item.split("=", 1)
        values[key] = value
    return values


def validate_client_runtime(config: dict, *, version: str, revision: str, created: str) -> None:
    values = environment_values(config)
    expected = {
        "HERMESSTATUS_CLIENT_VERSION": version,
        "HERMESSTATUS_CLIENT_REVISION": revision,
        "HERMESSTATUS_CLIENT_BUILD_TIME": created,
    }
    for key, value in expected.items():
        if values.get(key) != value:
            raise ValidationError("client runtime %s does not match the build input" % key)


def validate_component(config: dict, expected_component: str) -> None:
    labels = config.get("Labels") or {}
    if labels.get(COMPONENT_LABEL) != expected_component:
        raise ValidationError("image component label does not match the image role")


def parse_server_version(output: str) -> dict:
    match = re.fullmatch(r"serverstatus (?P<version>[^\s]+) commit=(?P<revision>[^\s]+) built=(?P<created>[^\s]+)\s*", output)
    if match is None:
        raise ValidationError("server --version output is invalid")
    return match.groupdict()


def validate_server_runtime_values(values: dict, *, version: str, revision: str, created: str) -> None:
    if values != {"version": version, "revision": revision, "created": created}:
        raise ValidationError("server runtime build values do not match the build input")


def validate_server_runtime(image: str, *, version: str, revision: str, created: str) -> None:
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "/usr/local/bin/serverstatus", image, "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    validate_server_runtime_values(
        parse_server_version(result.stdout), version=version, revision=revision, created=created
    )


def validate_inspect(
    inspect: dict,
    *,
    expected_title: str,
    expected_entrypoint: list,
    version: str,
    revision: str,
    created: str,
    source: str,
) -> dict:
    config = inspect.get("Config") or {}
    labels = config.get("Labels") or {}
    missing = [key for key in REQUIRED_LABELS if not labels.get(key)]
    if missing:
        raise ValidationError("missing required OCI labels: " + ", ".join(missing))

    if labels["org.opencontainers.image.title"] != expected_title:
        raise ValidationError("unexpected image title")
    if labels["org.opencontainers.image.version"] != version:
        raise ValidationError("image version does not match the build input")
    if labels["org.opencontainers.image.revision"] != revision:
        raise ValidationError("image revision does not match the build input")
    if labels["org.opencontainers.image.created"] != created:
        raise ValidationError("image creation time does not match the build input")
    if labels["org.opencontainers.image.source"] != source:
        raise ValidationError("image source does not match the build input")
    if labels["org.opencontainers.image.licenses"] != "MIT":
        raise ValidationError("unexpected image license label")
    if not SHA_PATTERN.fullmatch(revision):
        raise ValidationError("image revision must be a full lowercase Git SHA")
    validate_created(created)

    if config.get("Entrypoint") != expected_entrypoint:
        raise ValidationError("image entrypoint changed")
    for key, value in labels.items():
        rendered = "%s=%s" % (key, value)
        if SECRET_PATTERN.search(rendered):
            raise ValidationError("secret-like content detected in image labels")

    return {
        "image_id": inspect.get("Id"),
        "version": version,
        "revision": revision,
        "created": created,
        "source": source,
        "entrypoint": expected_entrypoint,
    }


def assert_no_git_directory(image: str) -> None:
    command = 'test -z "$(find / -type d -name .git -print -quit 2>/dev/null)"'
    subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "/bin/sh", image, "-c", command],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-image", required=True)
    parser.add_argument("--client-image", required=True)
    parser.add_argument("--candidate-tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--created", required=True)
    parser.add_argument("--source", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_candidate_tag(args.candidate_tag, args.version, args.revision)
        server_inspect = inspect_image(args.server_image)
        client_inspect = inspect_image(args.client_image)
        server = validate_inspect(
            server_inspect,
            expected_title="HermesStatus Server",
            expected_entrypoint=["/usr/local/bin/serverstatus"],
            version=args.version,
            revision=args.revision,
            created=args.created,
            source=args.source,
        )
        client = validate_inspect(
            client_inspect,
            expected_title="HermesStatus Client",
            expected_entrypoint=["/app/entrypoint.sh"],
            version=args.version,
            revision=args.revision,
            created=args.created,
            source=args.source,
        )
        validate_component(server_inspect.get("Config") or {}, "server")
        validate_component(client_inspect.get("Config") or {}, "client")
        validate_client_runtime(
            client_inspect.get("Config") or {},
            version=args.version,
            revision=args.revision,
            created=args.created,
        )
        validate_server_runtime(
            args.server_image,
            version=args.version,
            revision=args.revision,
            created=args.created,
        )
        assert_no_git_directory(args.server_image)
        assert_no_git_directory(args.client_image)
    except (ValidationError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print("image provenance validation failed: %s" % exc, file=sys.stderr)
        return 1

    print(json.dumps({"server": server, "client": client}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
