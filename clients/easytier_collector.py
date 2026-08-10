"""Strict, read-only EasyTier collector for HermesStatus 2.3.

The module deliberately accepts only the five inspection commands documented in
the 2.3 contract.  It never asks EasyTier for its configuration, credentials,
STUN data, or public endpoints, and it never returns command stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import time


DEFAULT_CLI_PATH = "/usr/local/bin/easytier-cli"
DEFAULT_RPC_PORTAL = "127.0.0.1:15888"
MAX_OUTPUT_BYTES = 512 * 1024
MAX_ITEMS = 256
SAFE_TEXT_LIMIT = 128
COMMANDS = (
    ("node_info", ("node", "info")),
    ("peer_list", ("peer", "list")),
    ("route_list", ("route", "list")),
    ("connector_list", ("connector", "list")),
    ("stats_show", ("stats", "show")),
)
ALLOWED_PORTALS = {"127.0.0.1:15888", "[::1]:15888"}
STATUS_VALUES = {
    "healthy", "degraded", "unavailable", "stale", "not_configured",
    "unsupported_version", "invalid_data",
}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _error(code, source="easytier"):
    messages = {
        "not_configured": "EasyTier monitoring is not configured",
        "easytier_cli_unavailable": "EasyTier CLI is unavailable",
        "rpc_unavailable": "EasyTier loopback RPC is unavailable",
        "command_failed": "EasyTier command is unavailable",
        "invalid_data": "EasyTier returned invalid monitoring data",
        "unsupported_version": "EasyTier version is not supported",
        "invalid_configuration": "EasyTier monitoring configuration is invalid",
        "partial_failure": "One or more EasyTier sources are unavailable",
    }
    return {
        "code": code,
        "message": messages.get(code, "EasyTier monitoring is unavailable"),
        "source": source,
        "retryable": code not in {"not_configured", "invalid_configuration"},
        "http_status": None,
    }


def _safe_text(value, limit=SAFE_TEXT_LIMIT):
    if not isinstance(value, (str, int, float, bool)) or isinstance(value, bool):
        return None
    value = str(value).strip()
    if not value or len(value) > limit:
        return None
    # The collector never emits URL-like values because those may be public
    # endpoints or contain credentials.
    if "://" in value or "@" in value or "token" in value.lower() or "secret" in value.lower():
        return None
    return value


def _counter(value):
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)) and 0 <= value <= 9007199254740991:
        return int(value)
    return 0


def _empty_command(status="not_configured", error=None):
    return {"status": status, "error": error}


def _empty_payload(status="not_configured", error=None):
    return {
        "status": status,
        "source": "easytier_cli" if status != "not_configured" else "unavailable",
        "node": {
            "state": "unknown", "instance_name": None, "network_name": None,
            "version": None, "peer_id": None,
        },
        "peers": {"total": 0, "direct": 0, "relay": 0, "unknown_path": 0},
        "routes": {"total": 0},
        "connectors": {"total": 0, "tcp_configured": False, "tcp_active": False},
        "traffic": {"bytes_rx": 0, "bytes_tx": 0, "bytes_forwarded": 0},
        "command_status": {name: _empty_command(status, error) for name, _ in COMMANDS},
        "updated_at": None,
        "stale": True,
        "error": error,
    }


def not_configured_easytier():
    return _empty_payload("not_configured", _error("not_configured"))


def _parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    value = str(value).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError("invalid boolean")


def _read_config(path):
    if not path:
        return {}
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
            raise ValueError("unsafe configuration file")
        data = os.read(descriptor, 65537)
        if len(data) > 65536:
            raise ValueError("configuration file too large")
    finally:
        os.close(descriptor)
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict) or set(value) - {"enabled", "cli_path", "rpc_portal", "timeout_seconds", "interval_seconds"}:
        raise ValueError("invalid configuration file")
    return value


def _parse_cli(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--easytier-enabled")
    parser.add_argument("--easytier-cli-path")
    parser.add_argument("--easytier-rpc-portal")
    parser.add_argument("--easytier-timeout-seconds")
    parser.add_argument("--easytier-interval-seconds")
    values, _ = parser.parse_known_args(argv or [])
    return {key: value for key, value in vars(values).items() if value is not None}


def load_easytier_config(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    file_values = _read_config(environ.get("EASYTIER_CONFIG_FILE"))
    env_values = {
        "enabled": environ.get("EASYTIER_ENABLED"),
        "cli_path": environ.get("EASYTIER_CLI_PATH"),
        "rpc_portal": environ.get("EASYTIER_RPC_PORTAL"),
        "timeout_seconds": environ.get("EASYTIER_TIMEOUT_SECONDS"),
        "interval_seconds": environ.get("EASYTIER_INTERVAL_SECONDS"),
    }
    cli_values = _parse_cli(argv)
    values = {
        "enabled": False,
        "cli_path": DEFAULT_CLI_PATH,
        "rpc_portal": DEFAULT_RPC_PORTAL,
        "timeout_seconds": 5,
        "interval_seconds": 30,
    }
    values.update({key: value for key, value in file_values.items() if value is not None})
    values.update({key: value for key, value in env_values.items() if value is not None})
    values.update({key.replace("easytier_", ""): value for key, value in cli_values.items()})
    values["enabled"] = _parse_bool(values["enabled"])
    values["timeout_seconds"] = int(values["timeout_seconds"])
    values["interval_seconds"] = int(values["interval_seconds"])
    if not 1 <= values["timeout_seconds"] <= 30 or not 5 <= values["interval_seconds"] <= 3600:
        raise ValueError("invalid timeout or interval")
    if values["rpc_portal"] not in ALLOWED_PORTALS:
        raise ValueError("rpc portal is not loopback")
    if not isinstance(values["cli_path"], str) or not os.path.isabs(values["cli_path"]):
        raise ValueError("CLI path must be absolute")
    return values


def _safe_cli_path(path):
    info = os.lstat(path)
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and bool(info.st_mode & 0o111)


def _json_object(output):
    if len(output) > MAX_OUTPUT_BYTES:
        raise ValueError("output too large")
    value = json.loads(output.decode("utf-8"))
    if not isinstance(value, (dict, list)):
        raise ValueError("output is not JSON")
    return value


def _as_list(value):
    if isinstance(value, list):
        return value[:MAX_ITEMS]
    if isinstance(value, dict):
        for key in ("peers", "routes", "connectors", "data", "items"):
            if isinstance(value.get(key), list):
                return value[key][:MAX_ITEMS]
    return []


def _lookup(value, *keys):
    if not isinstance(value, dict):
        return None
    for key in keys:
        if key in value:
            return value[key]
    return None


def _deep_lookup(value, *keys, _depth=0):
    direct = _lookup(value, *keys)
    if direct is not None:
        return direct
    if _depth >= 3:
        return None
    if isinstance(value, dict):
        for child in value.values():
            found = _deep_lookup(child, *keys, _depth=_depth + 1)
            if found is not None:
                return found
    return None


class EasyTierCollector(object):
    def __init__(self, argv=None, environ=None, runner=None):
        self.config = load_easytier_config(argv, environ)
        self.runner = runner or subprocess.run

    def _run(self, command):
        argv = [self.config["cli_path"], "-p", self.config["rpc_portal"], "-o", "json"] + list(command)
        result = self.runner(
            argv, shell=False, check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=self.config["timeout_seconds"],
        )
        if result.returncode != 0:
            raise RuntimeError("command failed")
        return _json_object(result.stdout)

    def collect(self):
        if not self.config["enabled"]:
            return not_configured_easytier()
        if not _safe_cli_path(self.config["cli_path"]):
            return _empty_payload("unavailable", _error("easytier_cli_unavailable"))

        payload = _empty_payload("healthy", None)
        successful = 0
        values = {}
        for name, command in COMMANDS:
            try:
                values[name] = self._run(command)
                payload["command_status"][name] = _empty_command("healthy", None)
                successful += 1
            except (OSError, subprocess.TimeoutExpired, RuntimeError):
                payload["command_status"][name] = _empty_command("unavailable", _error("command_failed", "easytier." + name))
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                payload["command_status"][name] = _empty_command("invalid_data", _error("invalid_data", "easytier." + name))

        if successful == 0:
            return _empty_payload("unavailable", _error("rpc_unavailable"))
        self._apply_node(payload, values.get("node_info"))
        self._apply_peers(payload, values.get("peer_list"), payload["node"]["peer_id"])
        self._apply_routes(payload, values.get("route_list"), payload["node"]["peer_id"])
        self._apply_connectors(payload, values.get("connector_list"))
        self._apply_stats(payload, values.get("stats_show"))
        payload["updated_at"] = _now()
        payload["stale"] = False
        version = payload["node"]["version"]
        if version and not version.startswith("2.6."):
            payload["status"] = "unsupported_version"
            payload["error"] = _error("unsupported_version")
        elif successful != len(COMMANDS):
            payload["status"] = "degraded"
            payload["error"] = _error("partial_failure")
        return payload

    @staticmethod
    def _apply_node(payload, value):
        if not isinstance(value, dict):
            return
        node = payload["node"]
        node["state"] = "running"
        node["instance_name"] = _safe_text(_deep_lookup(value, "instance_name", "hostname", "name"))
        node["network_name"] = _safe_text(_deep_lookup(value, "network_name"))
        node["version"] = _safe_text(_deep_lookup(value, "version"))
        peer_id = _deep_lookup(value, "peer_id", "virtual_peer_id")
        node["peer_id"] = _safe_text(peer_id, 32)

    @staticmethod
    def _apply_peers(payload, value, own_peer_id):
        peers = _as_list(value)
        result = payload["peers"]
        for peer in peers:
            peer_id = _safe_text(_lookup(peer, "peer_id", "virtual_peer_id", "id"), 32)
            if own_peer_id and peer_id == own_peer_id:
                continue
            result["total"] += 1
            path = str(_lookup(peer, "connection_type", "path", "route_type", "transport") or "").lower()
            if "relay" in path:
                result["relay"] += 1
            elif "direct" in path or "p2p" in path:
                result["direct"] += 1
            else:
                result["unknown_path"] += 1

    @staticmethod
    def _apply_routes(payload, value, own_peer_id):
        for route in _as_list(value):
            peer_id = _safe_text(_lookup(route, "peer_id", "virtual_peer_id", "id"), 32)
            path_len = _lookup(route, "path_len", "path_length")
            own_route = peer_id == own_peer_id or (isinstance(path_len, (int, float)) and not isinstance(path_len, bool) and path_len <= 0)
            if not own_route:
                payload["routes"]["total"] += 1

    @staticmethod
    def _apply_connectors(payload, value):
        connectors = _as_list(value)
        result = payload["connectors"]
        result["total"] = len(connectors)
        for connector in connectors:
            text = str(_lookup(connector, "protocol", "type", "url") or "").lower()
            is_tcp = text.startswith("tcp") or "tcp://" in text
            if is_tcp:
                result["tcp_configured"] = True
                if bool(_lookup(connector, "connected", "active", "is_connected")):
                    result["tcp_active"] = True

    @staticmethod
    def _apply_stats(payload, value):
        if not isinstance(value, dict):
            return
        traffic = payload["traffic"]
        network_name = _safe_text(_deep_lookup(value, "network_name"))
        if network_name is not None:
            payload["node"]["network_name"] = network_name
        traffic["bytes_rx"] = _counter(_lookup(value, "traffic_bytes_rx", "bytes_rx"))
        traffic["bytes_tx"] = _counter(_lookup(value, "traffic_bytes_tx", "bytes_tx"))
        traffic["bytes_forwarded"] = _counter(_lookup(value, "traffic_bytes_forwarded", "bytes_forwarded"))


def collector_from_environment(argv=None):
    try:
        return EasyTierCollector(argv=argv)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return _InvalidEasyTierCollector()


class _InvalidEasyTierCollector(object):
    def collect(self):
        return _empty_payload("unavailable", _error("invalid_configuration"))
