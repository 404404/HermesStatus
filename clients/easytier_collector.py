"""Strict, read-only EasyTier collector for HermesStatus 2.3.

The module deliberately accepts only the five inspection commands documented in
the 2.3 contract. It never asks EasyTier for its configuration or credentials,
and it never returns command stderr.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
import stat
import subprocess
import time
from urllib.parse import urlparse


DEFAULT_CLI_PATH = "/usr/local/bin/easytier-cli"
DEFAULT_RPC_PORTAL = "127.0.0.1:15888"
MAX_OUTPUT_BYTES = 512 * 1024
# The server's strict EasyTier projection cap is 64 KiB. All retained data is
# bounded before it reaches the Device v2 payload.
MAX_ITEMS = 16
MAX_STATS_ITEMS = 64
SAFE_TEXT_LIMIT = 128
MAX_COMMAND_DURATION_MS = 30000
# EasyTier 2.6.4 exposes these five stable, read-only JSON commands. Route is
# collected independently so a transient route failure cannot poison node,
# peer, connector, or traffic observations.
COMMANDS = (
    ("node_info", ("node",)),
    ("peer_list", ("peer",)),
    ("route_list", ("route",)),
    ("connector_list", ("connector",)),
    ("stats_show", ("stats",)),
)
COMMAND_STATUS_NAMES = ("node_info", "peer_list", "route_list", "connector_list", "stats_show")
ALLOWED_PORTALS = {"127.0.0.1:15888", "[::1]:15888"}
STATUS_VALUES = {
    "healthy", "degraded", "unavailable", "stale", "not_configured",
    "unsupported_version", "invalid_data",
}
TRANSPORTS = {"udp", "tcp", "quic", "wg", "wss", "unknown"}
FAMILIES = {"ipv4", "ipv6", "unknown"}
INTERNAL_IPV4_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
INTERNAL_CIDR_NETWORKS = INTERNAL_IPV4_NETWORKS + (ipaddress.ip_network("fc00::/7"),)


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


def _safe_metric_label_name(value):
    value = _safe_text(value, 64)
    return value if value and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) else None


def _safe_listener(value):
    """Retain a bounded listener only when it cannot carry credentials.

    Node listeners are useful local topology facts, but the raw node object
    also contains configuration. Never retain arbitrary URL text from it.
    """
    if not isinstance(value, str) or len(value) > SAFE_TEXT_LIMIT:
        return None
    if "token" in value.lower() or "secret" in value.lower():
        return None
    parsed = urlparse(value)
    if (
        not parsed.scheme or not parsed.netloc or parsed.username or parsed.password
        or parsed.query or parsed.fragment or "@" in parsed.netloc
    ):
        return None
    scheme = _transport(parsed.scheme)
    if scheme == "unknown":
        return None
    host = parsed.hostname
    if not host:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None or port < 1 or port > 65535:
        return None
    rendered_host = "[%s]" % host if ":" in host else host
    return "%s://%s:%d" % (scheme, rendered_host, port)


def _nullable_number(value, maximum, percent=False):
    if isinstance(value, str):
        value = value.strip()
        if value == "-":
            return None
        if percent and value.endswith("%"):
            value = value[:-1].strip()
        try:
            value = float(value)
        except ValueError:
            return None
    return _bounded_number(value, maximum, True)


def _counter(value):
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 9007199254740991:
        return int(value)
    return 0


def _bounded_number(value, maximum, decimals=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > maximum:
        return None
    return float(value) if decimals else int(value)


def _internal_ip(value):
    text = _safe_text(value, 64)
    if text is None:
        return None
    try:
        address = ipaddress.ip_interface(text).ip if "/" in text else ipaddress.ip_address(text)
    except ValueError:
        return None
    return str(address) if address.version == 4 and any(address in network for network in INTERNAL_IPV4_NETWORKS) else None


def _internal_cidrs(value):
    raw = value if isinstance(value, list) else [value]
    result = []
    for item in raw[:16]:
        text = _safe_text(item, 64)
        if text is None:
            continue
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError:
            continue
        if any(network.version == allowed.version and network.subnet_of(allowed) for allowed in INTERNAL_CIDR_NETWORKS) and str(network) not in result:
            result.append(str(network))
    return result


def _transport(value):
    text = str(value or "").strip().lower()
    for candidate in ("udp", "tcp", "quic", "wg", "wss"):
        if text == candidate or text.startswith(candidate + ":") or text.startswith(candidate + "//"):
            return candidate
    return "unknown"


def _family(value, address=None):
    text = str(value or "").strip().lower()
    if text in FAMILIES:
        return text
    if address:
        try:
            return "ipv6" if ipaddress.ip_address(address).version == 6 else "ipv4"
        except ValueError:
            pass
    return "unknown"


def _empty_command(status="not_configured", error=None):
    return {"status": status, "last_success_at": None, "collected_at": None, "duration_ms": None, "error": error}


def _command_duration_ms(started, ended=None):
    if ended is None:
        ended = time.monotonic()
    return min(MAX_COMMAND_DURATION_MS, max(0, int((ended - started) * 1000)))


def _empty_payload(status="not_configured", error=None):
    command_status = {name: _empty_command(status, error) for name in COMMAND_STATUS_NAMES}
    return {
        "status": status,
        "source": "easytier_cli" if status != "not_configured" else "unavailable",
        "node": {
            "state": "unknown", "instance_name": None, "network_name": None,
            "version": None, "peer_id": None, "overlay_ipv4": None, "proxy_cidrs": [], "administrative_role": None,
            "hostname": None, "inst_id": None, "listeners": [],
            "stun_info": {"udp_nat_type": None, "tcp_nat_type": None, "public_ips": [], "last_update_time": None},
            "schema_compatibility": "unknown",
        },
        "peers": {"total": 0, "direct": 0, "relay": 0, "unknown_path": 0, "ipv6_udp_direct": None, "items": []},
        "routes": {"total": 0, "items": []},
        "connectors": {"total": 0, "tcp_configured": False, "tcp_active": False, "tcp_listener_available": None, "items": []},
        "traffic": {
            "bytes_rx": 0, "bytes_tx": 0, "bytes_forwarded": 0,
            "packets_rx": 0, "packets_tx": 0,
            "rx_bps": None, "tx_bps": None, "by_instance": [], "samples": [],
        },
        "command_status": command_status,
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
    if not isinstance(value, dict) or set(value) - {"enabled", "cli_path", "rpc_portal", "timeout_seconds", "interval_seconds", "administrative_role"}:
        raise ValueError("invalid configuration file")
    return value


def _parse_cli(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--easytier-enabled")
    parser.add_argument("--easytier-cli-path")
    parser.add_argument("--easytier-rpc-portal")
    parser.add_argument("--easytier-timeout-seconds")
    parser.add_argument("--easytier-interval-seconds")
    parser.add_argument("--easytier-administrative-role")
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
        "administrative_role": environ.get("EASYTIER_ADMINISTRATIVE_ROLE"),
    }
    cli_values = _parse_cli(argv)
    values = {
        "enabled": False,
        "cli_path": DEFAULT_CLI_PATH,
        "rpc_portal": DEFAULT_RPC_PORTAL,
        "timeout_seconds": 5,
        "interval_seconds": 30,
        "administrative_role": None,
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
    if values["administrative_role"] not in {None, "site_router", "endpoint", "bootstrap_listener", "relay_capable", "observer"}:
        raise ValueError("invalid EasyTier administrative role")
    return values


def _safe_cli_path(path):
    info = os.lstat(path)
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and bool(info.st_mode & 0o111)


def _json_object(output):
    if len(output) > MAX_OUTPUT_BYTES:
        raise ValueError("output too large")
    value = json.loads(output.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON number")))
    if not isinstance(value, (dict, list)):
        raise ValueError("output is not JSON")
    return value


def _list_payload(value, keys):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in keys:
            if isinstance(value.get(key), list):
                return value[key]
    return None


def _metric_samples(value):
    if not isinstance(value, list) or len(value) > MAX_STATS_ITEMS:
        return None
    result = []
    identities = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _safe_text(item.get("name"), 64)
        metric = item.get("value")
        labels = item.get("labels", {})
        if (
            name is None or isinstance(metric, bool) or not isinstance(metric, (int, float))
            or not math.isfinite(metric) or not 0 <= metric <= 9007199254740991
            or not isinstance(labels, dict) or len(labels) > 8
        ):
            continue
        clean_labels = {}
        malformed = False
        for key, label_value in labels.items():
            safe_key, safe_value = _safe_metric_label_name(key), _safe_text(label_value, 64)
            if safe_key is None or safe_value is None:
                malformed = True
                break
            clean_labels[safe_key] = safe_value
        if malformed:
            continue
        identity = (name, tuple(sorted(clean_labels.items())))
        if identity in identities:
            continue
        identities.add(identity)
        result.append({"name": name, "value": int(metric), "labels": clean_labels})
    return result


def _metric_value(samples, name, labels=None):
    labels = labels or {}
    matches = [
        item["value"] for item in samples
        if item["name"] == name and item["labels"] == labels
    ]
    return matches[0] if len(matches) == 1 else None


def _network_names(samples):
    return sorted({item["labels"].get("network_name") for item in samples if item["labels"].get("network_name")})


def _valid_command_payload(name, value):
    if name == "node_info":
        return isinstance(value, dict) and _safe_text(_lookup(value, "peer_id"), 32) is not None and _safe_text(_lookup(value, "version")) is not None
    if name == "peer_list":
        items = _list_payload(value, ("peers", "data", "items"))
        return items is not None and len(items) <= MAX_ITEMS and all(isinstance(item, dict) and _safe_text(_lookup(item, "peer_id", "virtual_peer_id", "id"), 32) is not None for item in items)
    if name == "route_list":
        items = _list_payload(value, ("routes", "data", "items"))
        return items is not None and len(items) <= MAX_ITEMS and all(
            isinstance(item, dict) and (
                _safe_text(_lookup(item, "peer_id", "virtual_peer_id", "id"), 32) is not None
                or _internal_ip(_lookup(item, "overlay_ipv4", "virtual_ipv4", "ipv4")) is not None
            )
            for item in items
        )
    if name == "connector_list":
        items = _list_payload(value, ("connectors", "data", "items"))
        return items is not None and len(items) <= MAX_ITEMS and all(isinstance(item, dict) for item in items)
    if name == "stats_show":
        metrics = _metric_samples(value)
        networks = _network_names(metrics or [])
        return metrics is not None and len(networks) == 1 and all(
            _metric_value(metrics, key, {"network_name": networks[0]}) is not None
            for key in ("traffic_bytes_rx", "traffic_bytes_tx", "traffic_packets_rx", "traffic_packets_tx")
        )
    return False


def _as_list(value):
    if isinstance(value, list):
        return value[:MAX_ITEMS]
    if isinstance(value, dict):
        for key in ("peers", "routes", "connectors", "data", "items"):
            if isinstance(value.get(key), list):
                return value[key][:MAX_ITEMS]
    return []


def _as_scalar_list(value):
    return value[:MAX_ITEMS] if isinstance(value, list) else [value]


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
    def __init__(self, argv=None, environ=None, runner=None, clock=None):
        self.config = load_easytier_config(argv, environ)
        self.runner = runner or subprocess.run
        self.clock = clock or time.monotonic
        self._previous_traffic = None

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
            started = self.clock()
            collected_at = _now()
            try:
                value = self._run(command)
                # node.config contains network_secret. Strip it immediately
                # after JSON decoding, before validation, caching, or error
                # handling can retain a reference to the raw object.
                if name == "node_info" and isinstance(value, dict):
                    value = {key: item for key, item in value.items() if key != "config"}
                if not _valid_command_payload(name, value):
                    raise ValueError("invalid command payload")
                values[name] = value
                command_status = _empty_command("healthy", None)
                command_status["last_success_at"] = collected_at
                command_status["collected_at"] = collected_at
                command_status["duration_ms"] = _command_duration_ms(started, self.clock())
                payload["command_status"][name] = command_status
                successful += 1
            except (OSError, subprocess.TimeoutExpired, RuntimeError):
                command_status = _empty_command("unavailable", _error("command_failed", "easytier." + name))
                command_status["collected_at"] = collected_at
                command_status["duration_ms"] = _command_duration_ms(started, self.clock())
                payload["command_status"][name] = command_status
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                command_status = _empty_command("invalid_data", _error("invalid_data", "easytier." + name))
                command_status["collected_at"] = collected_at
                command_status["duration_ms"] = _command_duration_ms(started, self.clock())
                payload["command_status"][name] = command_status

        if successful == 0:
            return _empty_payload("unavailable", _error("rpc_unavailable"))
        self._apply_node(payload, values.get("node_info"))
        self._apply_peers(payload, values.get("peer_list"), payload["node"]["peer_id"])
        self._apply_routes(payload, values.get("route_list"), payload["node"]["peer_id"], payload["node"]["overlay_ipv4"])
        self._apply_connectors(payload, values.get("connector_list"))
        self._apply_stats(payload, values.get("stats_show"), self.clock())
        payload["updated_at"] = _now()
        payload["stale"] = False
        version = payload["node"]["version"]
        payload["node"]["schema_compatibility"] = "supported" if version and version.startswith("2.6.") else "unknown"
        if version and not version.startswith("2.6."):
            payload["node"]["schema_compatibility"] = "unsupported"
            payload["status"] = "unsupported_version"
            payload["error"] = _error("unsupported_version")
        elif successful != len(COMMANDS):
            payload["status"] = "degraded"
            payload["error"] = _error("partial_failure")
        return payload

    def _apply_node(self, payload, value):
        if not isinstance(value, dict):
            return
        node = payload["node"]
        node["state"] = "running"
        hostname = _safe_text(_lookup(value, "hostname"))
        node["hostname"] = hostname
        # Existing UI reads these aliases until its later, separately approved
        # layout pass. They carry the same safe node facts.
        node["instance_name"] = hostname
        node["inst_id"] = _safe_text(_lookup(value, "inst_id"), 64)
        node["version"] = _safe_text(_lookup(value, "version"))
        peer_id = _lookup(value, "peer_id")
        node["peer_id"] = _safe_text(peer_id, 32)
        node["overlay_ipv4"] = _internal_ip(_lookup(value, "ipv4_addr"))
        node["proxy_cidrs"] = _internal_cidrs(_lookup(value, "proxy_cidrs", "proxy_cidr"))
        # The role is an explicit operator declaration from the Client's
        # non-secret monitoring config. It never comes from node.config, which
        # contains the EasyTier network_secret.
        node["administrative_role"] = self.config["administrative_role"]
        node["listeners"] = [item for item in (_safe_listener(item) for item in _as_list(_lookup(value, "listeners"))) if item]
        stun = _lookup(value, "stun_info")
        if isinstance(stun, dict):
            node["stun_info"] = {
                "udp_nat_type": _safe_text(_lookup(stun, "udp_nat_type")),
                "tcp_nat_type": _safe_text(_lookup(stun, "tcp_nat_type")),
                "public_ips": [item for item in (_safe_text(item, 64) for item in _as_scalar_list(_lookup(stun, "public_ip"))) if item],
                "last_update_time": _safe_text(_lookup(stun, "last_update_time"), 40),
            }
        for listener in node["listeners"]:
            if listener.startswith("tcp://"):
                payload["connectors"]["tcp_listener_available"] = True

    @staticmethod
    def _apply_peers(payload, value, own_peer_id):
        peers = _as_list(value)
        result = payload["peers"]
        for peer in peers:
            peer_id = _safe_text(_lookup(peer, "id"), 32)
            overlay_ipv4 = _internal_ip(_lookup(peer, "ipv4"))
            cost = _safe_text(_lookup(peer, "cost"), 64)
            normalized_cost = (cost or "").lower()
            path_state = "direct" if normalized_cost == "p2p" else "relayed" if "relay" in normalized_cost else "unknown"
            tunnels = []
            raw_tunnels = _safe_text(_lookup(peer, "tunnel_proto"), 128)
            if raw_tunnels:
                for item in raw_tunnels.split(","):
                    item = item.strip().lower()
                    if item and re.fullmatch(r"[a-z0-9]{1,16}", item) and item not in tunnels:
                        tunnels.append(item)
            transport = _transport(tunnels[0] if tunnels else None)
            family = "ipv6" if any(item.endswith("6") for item in tunnels) else "unknown"
            item = {
                "peer_id": peer_id,
                "overlay_ipv4": overlay_ipv4,
                "hostname": _safe_text(_lookup(peer, "hostname")),
                "version": _safe_text(_lookup(peer, "version")),
                "cost": cost,
                "established_tunnels": tunnels,
                "nat_type": _safe_text(_lookup(peer, "nat_type"), 64),
                "path_state": path_state,
                "transport": transport,
                "address_family": family,
                "locally_initiated": False,
                "latency_ms": _nullable_number(_lookup(peer, "lat_ms"), 600000),
                "loss_rate": _nullable_number(_lookup(peer, "loss_rate"), 100, percent=True),
                # CLI values are formatted text, not monotonic counters. Keep
                # the display values separately and never use them for rates.
                "rx_display": _safe_text(_lookup(peer, "rx_bytes"), 64),
                "tx_display": _safe_text(_lookup(peer, "tx_bytes"), 64),
                "rx_bytes": 0,
                "tx_bytes": 0,
                "rx_packets": _counter(_lookup(peer, "rx_packets")),
                "tx_packets": _counter(_lookup(peer, "tx_packets")),
                "closed": bool(_lookup(peer, "closed", "is_closed")),
            }
            result["items"].append(item)
            result["total"] += 1
            if path_state == "relayed":
                result["relay"] += 1
            elif path_state == "direct":
                result["direct"] += 1
            else:
                result["unknown_path"] += 1
        if result["total"] and all(item["path_state"] != "unknown" and item["transport"] != "unknown" and item["address_family"] != "unknown" for item in result["items"]):
            result["ipv6_udp_direct"] = any(
                item["path_state"] == "direct" and item["transport"] == "udp" and item["address_family"] == "ipv6"
                for item in result["items"]
            )

    @staticmethod
    def _apply_routes(payload, value, own_peer_id, own_overlay_ipv4=None):
        for route in _as_list(value):
            peer_id = _safe_text(_lookup(route, "peer_id", "virtual_peer_id", "id"), 32)
            overlay_ipv4 = _internal_ip(_lookup(route, "overlay_ipv4", "virtual_ipv4", "ipv4"))
            next_hop = _safe_text(_lookup(route, "next_hop_peer_id", "next_hop", "next_hop_hostname", "next_hop_ipv4"), 128)
            evidence = str(_lookup(route, "connection_type", "path", "route_type") or "").lower()
            path_state = "unknown"
            if peer_id and next_hop and peer_id == next_hop and ("direct" in evidence or "p2p" in evidence):
                path_state = "direct"
            elif peer_id and next_hop and peer_id != next_hop:
                path_state = "relayed"
            own_route = (
                (peer_id is not None and own_peer_id is not None and peer_id == own_peer_id)
                or (peer_id is None and own_overlay_ipv4 is not None and overlay_ipv4 == own_overlay_ipv4)
            )
            payload["routes"]["total"] += 1
            payload["routes"]["items"].append({
                    "peer_id": peer_id,
                    "overlay_ipv4": overlay_ipv4,
                    "hostname": _safe_text(_lookup(route, "hostname", "name")),
                    "version": _safe_text(_lookup(route, "version")),
                    "next_hop_peer_id": next_hop,
                    "cost": _bounded_number(_lookup(route, "cost", "path_len"), 1000000),
                    "path_latency_ms": _bounded_number(_lookup(route, "path_latency_ms", "path_latency", "latency_ms"), 600000, True),
                    "proxy_cidrs": _internal_cidrs(_lookup(route, "proxy_cidrs", "proxy_cidr", "cidrs")),
                    "path_state": path_state,
                    "is_local": own_route,
                })

    @staticmethod
    def _apply_connectors(payload, value):
        connectors = _as_list(value)
        result = payload["connectors"]
        result["total"] = len(connectors)
        for connector in connectors:
            raw_url = _lookup(_lookup(connector, "url"), "url")
            safe_url = _safe_listener(raw_url)
            parsed = urlparse(safe_url) if safe_url else None
            transport = _transport(parsed.scheme if parsed else None)
            is_tcp = transport == "tcp"
            port = parsed.port if parsed else None
            host = parsed.hostname if parsed else None
            endpoint = (("[%s]" % host if host and ":" in host else host) + (":%d" % port if host and port else "")) if host else None
            raw_status = _bounded_number(_lookup(connector, "status"), 2147483647)
            active = raw_status == 0
            result["items"].append({
                "url": safe_url,
                "endpoint": endpoint,
                "transport": transport,
                "address_family": _family(None, host),
                "port": port,
                "raw_status": raw_status,
                "status": "connected" if active else "unknown",
            })
            if is_tcp:
                result["tcp_configured"] = True
                if active:
                    result["tcp_active"] = True

    def _apply_stats(self, payload, value, collected_monotonic):
        metrics = _metric_samples(value)
        if metrics is None:
            return
        traffic = payload["traffic"]
        traffic["samples"] = metrics
        networks = _network_names(metrics)
        if len(networks) == 1:
            payload["node"]["network_name"] = networks[0]
        labels = {"network_name": networks[0]} if len(networks) == 1 else {}
        for field, metric_name in (
            ("bytes_rx", "traffic_bytes_rx"), ("bytes_tx", "traffic_bytes_tx"),
            ("bytes_forwarded", "traffic_bytes_forwarded"), ("packets_rx", "traffic_packets_rx"),
            ("packets_tx", "traffic_packets_tx"),
        ):
            metric = _metric_value(metrics, metric_name, labels)
            if metric is not None:
                traffic[field] = metric

        grouped = {}
        for sample in metrics:
            if sample["name"] not in {
                "traffic_bytes_rx_by_instance", "traffic_bytes_tx_by_instance",
                "traffic_packets_rx_by_instance", "traffic_packets_tx_by_instance",
            }:
                continue
            sample_labels = sample["labels"]
            key = tuple((name, sample_labels.get(name)) for name in ("network_name", "from_instance_id", "to_instance_id"))
            row = grouped.setdefault(key, {"network_name": sample_labels.get("network_name"), "from_instance_id": sample_labels.get("from_instance_id"), "to_instance_id": sample_labels.get("to_instance_id"), "bytes_rx": None, "bytes_tx": None, "packets_rx": None, "packets_tx": None})
            row[{"traffic_bytes_rx_by_instance": "bytes_rx", "traffic_bytes_tx_by_instance": "bytes_tx", "traffic_packets_rx_by_instance": "packets_rx", "traffic_packets_tx_by_instance": "packets_tx"}[sample["name"]]] = sample["value"]
        traffic["by_instance"] = list(grouped.values())[:MAX_ITEMS]

        current = (traffic["bytes_rx"], traffic["bytes_tx"], collected_monotonic)
        previous = self._previous_traffic
        self._previous_traffic = current
        if previous is None:
            return
        old_rx, old_tx, old_at = previous
        interval = collected_monotonic - old_at
        if interval <= 0 or traffic["bytes_rx"] < old_rx or traffic["bytes_tx"] < old_tx:
            return
        traffic["rx_bps"] = (traffic["bytes_rx"] - old_rx) * 8.0 / interval
        traffic["tx_bps"] = (traffic["bytes_tx"] - old_tx) * 8.0 / interval


def collector_from_environment(argv=None):
    try:
        return EasyTierCollector(argv=argv)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return _InvalidEasyTierCollector()


class _InvalidEasyTierCollector(object):
    def collect(self):
        return _empty_payload("unavailable", _error("invalid_configuration"))
