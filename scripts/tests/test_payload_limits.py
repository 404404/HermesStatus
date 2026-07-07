#!/usr/bin/env python3
import importlib.util
import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "clients" / "client-psutil.py"
NET_MAX_PACKETSIZE = 65536


def load_client():
    sys.modules.setdefault("psutil", types.ModuleType("psutil"))
    spec = importlib.util.spec_from_file_location("client_psutil", CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def long_containers(count):
    return {
        "running": count,
        "total": count,
        "containers": [
            {
                "id": ("%012x" % i),
                "image": "example/very-long-image-name:2026.07.03",
                "command": "python worker.py --profile hermes%d --note %s" % (i, "x" * 120),
                "created": "4 hours ago",
                "status": "Up 4 hours (healthy)",
                "state": "running",
                "ports": "0.0.0.0:%d->80/tcp" % (20000 + i),
                "names": "hermes-worker-%d" % i,
            }
            for i in range(count)
        ],
    }


def long_profiles(count):
    return {
        "profiles": [
            {
                "profile": "hermes%d" % i,
                "api_status": "healthy",
                "service_status": "healthy",
                "gateway_service": "running",
                "manager_mode": "docker (foreground)",
                "model": "gemini-2.5-flash",
                "usage_mode": "api",
                "provider": "Google AI Studio",
                "auth_refreshed_at": "2026-07-01 21:48:10 CST",
                "scheduled_jobs_active": i % 9,
                "scheduled_jobs_total": i % 9,
                "sessions_active": i % 11,
                "usage": {
                    "input_tokens": 18004 + i,
                    "output_tokens": 6842 + i,
                    "total_tokens": 24846 + i * 2,
                },
                "note": "x" * 240,
            }
            for i in range(count)
        ],
    }


def main():
    client = load_client()
    docker_json = client._json_compact_limited(
        long_containers(200),
        client.DOCKER_JSON_MAX_BYTES,
        "containers",
        {"running": 0, "total": 0, "containers": []},
    )
    hermes_json = client._json_compact_limited(
        long_profiles(200),
        client.HERMES_JSON_MAX_BYTES,
        "profiles",
        {"profiles": []},
    )
    payload = {
        "uptime": 1,
        "load_1": 0.1,
        "load_5": 0.1,
        "load_15": 0.1,
        "memory_total": 1,
        "memory_used": 1,
        "swap_total": 0,
        "swap_used": 0,
        "hdd_total": 1,
        "hdd_used": 1,
        "cpu": 1,
        "network_rx": 0,
        "network_tx": 0,
        "network_in": 0,
        "network_out": 0,
        "ping_10010": 0,
        "ping_189": 0,
        "ping_10086": 0,
        "time_10010": 0,
        "time_189": 0,
        "time_10086": 0,
        "tcp": 0,
        "udp": 0,
        "process": 0,
        "thread": 0,
        "io_read": 0,
        "io_write": 0,
        "os": "Ubuntu 22.04.5 LTS (Jammy Jellyfish)",
        "custom": "",
        "hardware_json": client._json_compact({"disk_smart_status": "passed"}),
        "docker_json": docker_json,
        "hermes_json": hermes_json,
    }
    wire = ("update " + json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    assert len(docker_json.encode("utf-8")) <= client.DOCKER_JSON_MAX_BYTES
    assert len(hermes_json.encode("utf-8")) <= client.HERMES_JSON_MAX_BYTES
    assert len(wire) < NET_MAX_PACKETSIZE, len(wire)
    print(json.dumps({
        "docker_json_bytes": len(docker_json.encode("utf-8")),
        "hermes_json_bytes": len(hermes_json.encode("utf-8")),
        "wire_bytes": len(wire),
        "packet_limit": NET_MAX_PACKETSIZE,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
