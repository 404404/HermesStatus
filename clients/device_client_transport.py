"""Shared fixed HermesStatus device_v2 HTTPS transport and retry runtime."""

from __future__ import annotations

import http.client
import ipaddress
import itertools
import json
import random
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from device_client_config import load_custom_ca, load_device_token
from multi_device_contracts import (
    MAX_RESPONSE_BYTES,
    UPDATE_PATH,
    ClientContractError,
    ClientV2Config,
    build_envelope,
    decode_success_response,
    encode_envelope,
    retry_delay_seconds,
)


SLOW_RETRY_CODES = {
    "payload_incompatible",
    "authorization_rejected",
    "endpoint_unavailable",
    "payload_too_large",
    "protocol_incompatible",
    "redirect_rejected",
    "invalid_server_response",
}
DISCARDED_REPORT_CODES = {"stale_report", "report_conflict"}
_MONITOR_GENERATIONS = itertools.count(1)


class DeviceTransportError(Exception):
    def __init__(
        self,
        code: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after_seconds = retry_after_seconds

    def __repr__(self) -> str:
        return f"DeviceTransportError({self.code!r})"


class MonitorCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation: str | None = None
        self._monitors: tuple[dict[str, Any], ...] = ()

    def update(self, response: Mapping[str, Any]) -> None:
        monitors = tuple(dict(item) for item in response["monitors"])
        with self._lock:
            self._generation = str(response["config_generation"])
            self._monitors = monitors

    def snapshot(self) -> tuple[str | None, list[dict[str, Any]]]:
        with self._lock:
            return self._generation, [dict(item) for item in self._monitors]


class DeviceHTTPSClient:
    __slots__ = ("_config", "_token", "_context", "_connection_factory")

    def __init__(
        self,
        config: ClientV2Config,
        *,
        connection_factory: Callable[
            [ClientV2Config, ssl.SSLContext | None], Any
        ]
        | None = None,
    ) -> None:
        self._config = config
        self._token = load_device_token(config.token_file)
        self._context = build_tls_context(config)
        self._connection_factory = connection_factory or _new_connection

    def __repr__(self) -> str:
        return "<DeviceHTTPSClient device_v2>"

    def send(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        device = envelope.get("device")
        if not isinstance(device, Mapping) or device.get("id") != self._config.device_id:
            raise DeviceTransportError("local_identity_mismatch")
        try:
            rebuilt = build_envelope(
                self._config,
                collected_at=envelope.get("collected_at"),
                stats=envelope.get("stats"),
                hostname=device.get("hostname"),
            )
            if dict(envelope) != rebuilt:
                raise ClientContractError("envelope fields are invalid")
            body = encode_envelope(rebuilt)
        except ClientContractError:
            raise DeviceTransportError("payload_incompatible") from None
        connection = self._connection_factory(self._config, self._context)
        try:
            connection.connect()
            if getattr(connection, "sock", None) is not None:
                connection.sock.settimeout(self._config.read_timeout_seconds)
            connection.request(
                "POST",
                UPDATE_PATH,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": "Bearer " + self._token,
                    "X-HermesStatus-Device-ID": self._config.device_id,
                },
            )
            response = connection.getresponse()
            data = _read_bounded_response(response)
            return _classify_response(response, data)
        except DeviceTransportError:
            raise
        except ssl.SSLCertVerificationError:
            raise DeviceTransportError("tls_verification_failed") from None
        except ssl.SSLError:
            raise DeviceTransportError("tls_failed") from None
        except (socket.timeout, TimeoutError):
            raise DeviceTransportError("transport_timeout") from None
        except (ConnectionError, OSError, http.client.HTTPException):
            raise DeviceTransportError("transport_unavailable") from None
        finally:
            try:
                connection.close()
            except Exception:
                pass


def build_tls_context(config: ClientV2Config) -> ssl.SSLContext | None:
    parsed = urlsplit(config.server_url)
    if parsed.scheme == "http":
        if not config.loopback_test_profile or not _is_loopback_host(parsed.hostname):
            raise ClientContractError("plain HTTP is unavailable")
        return None
    if parsed.scheme != "https" or not config.verify_tls:
        raise ClientContractError("verified HTTPS is required")
    ca_data = load_custom_ca(config.ca_file)
    try:
        context = ssl.create_default_context(cadata=ca_data)
    except ssl.SSLError as exc:
        raise ClientContractError("custom CA file is invalid") from exc
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _new_connection(
    config: ClientV2Config,
    context: ssl.SSLContext | None,
) -> http.client.HTTPConnection:
    parsed = urlsplit(config.server_url)
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(
            parsed.hostname,
            parsed.port or 443,
            timeout=config.connect_timeout_seconds,
            context=context,
        )
    if (
        parsed.scheme == "http"
        and config.loopback_test_profile
        and _is_loopback_host(parsed.hostname)
    ):
        return http.client.HTTPConnection(
            parsed.hostname,
            parsed.port or 80,
            timeout=config.connect_timeout_seconds,
        )
    raise ClientContractError("transport origin is invalid")


def _is_loopback_host(value: str | None) -> bool:
    if value == "localhost":
        return True
    if value is None:
        return False
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _read_bounded_response(response: Any) -> bytes:
    length_value = response.getheader("Content-Length")
    if length_value is not None:
        try:
            length = int(length_value)
        except (TypeError, ValueError):
            raise DeviceTransportError("invalid_server_response") from None
        if length < 0 or length > MAX_RESPONSE_BYTES:
            raise DeviceTransportError("invalid_server_response")
    try:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    except (http.client.IncompleteRead, OSError):
        raise DeviceTransportError("transport_unavailable") from None
    if len(data) > MAX_RESPONSE_BYTES:
        raise DeviceTransportError("invalid_server_response")
    return data


def _classify_response(response: Any, data: bytes) -> dict[str, Any]:
    status = int(response.status)
    if 300 <= status <= 399:
        raise DeviceTransportError("redirect_rejected")
    if status == 202:
        if not _valid_json_content_type(response.getheader("Content-Type")):
            raise DeviceTransportError("invalid_server_response")
        try:
            return decode_success_response(data)
        except ClientContractError:
            raise DeviceTransportError("invalid_server_response") from None
    if status == 400:
        raise DeviceTransportError("payload_incompatible")
    if status in (401, 403):
        raise DeviceTransportError("authorization_rejected")
    if status == 404:
        raise DeviceTransportError("endpoint_unavailable")
    if status == 413:
        raise DeviceTransportError("payload_too_large")
    if status == 415:
        raise DeviceTransportError("protocol_incompatible")
    if status == 409:
        raise DeviceTransportError(_conflict_error_code(data))
    if status == 429:
        raise DeviceTransportError(
            "rate_limited",
            retry_after_seconds=_bounded_retry_after(response),
        )
    if 500 <= status <= 599:
        raise DeviceTransportError("server_unavailable")
    raise DeviceTransportError("unexpected_server_status")


def _conflict_error_code(data: bytes) -> str:
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "report_conflict"
    if not isinstance(document, dict) or set(document) != {"error"}:
        return "report_conflict"
    error = document["error"]
    if not isinstance(error, dict) or set(error) != {"code", "request_id"}:
        return "report_conflict"
    code = error["code"]
    if code in DISCARDED_REPORT_CODES:
        return code
    return "report_conflict"


def _valid_json_content_type(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    parts = [part.strip() for part in value.split(";")]
    if not parts or len(parts) > 2 or parts[0].lower() != "application/json":
        return False
    for parameter in parts[1:]:
        key, separator, parameter_value = parameter.partition("=")
        if (
            not separator
            or key.strip().lower() != "charset"
            or parameter_value.strip().strip('"').lower() != "utf-8"
        ):
            return False
    return True


def _bounded_retry_after(response: Any) -> float | None:
    headers = response.headers
    values = headers.get_all("Retry-After") if hasattr(headers, "get_all") else None
    if values is None:
        value = response.getheader("Retry-After")
        values = [] if value is None else [value]
    if len(values) != 1:
        return None
    try:
        seconds = int(values[0])
    except (TypeError, ValueError):
        return None
    if not 1 <= seconds <= 300:
        return None
    return float(seconds)


@dataclass
class DeviceV2Runner:
    config: ClientV2Config
    collect_stats: Callable[[], Mapping[str, Any]]
    apply_monitors: Callable[[list[dict[str, Any]]], None]
    client: DeviceHTTPSClient
    cache: MonitorCache
    random_value: Callable[[], float] = random.random
    logger: Callable[[str], None] = print
    monotonic: Callable[[], float] = time.monotonic
    attempt: int = 0
    _last_log_code: str | None = None
    _last_log_at: float = 0.0

    def run_once(self) -> float:
        try:
            stats = self.collect_stats()
            collected_at = (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
            envelope = build_envelope(
                self.config,
                collected_at=collected_at,
                stats=stats,
                hostname=socket.gethostname(),
            )
            response = self.client.send(envelope)
            self.cache.update(response)
            _, monitors = self.cache.snapshot()
            self.apply_monitors(monitors)
            self.attempt = 0
            return float(self.config.collection_interval_seconds)
        except DeviceTransportError as exc:
            self._log_throttled(exc.code)
            if exc.code in DISCARDED_REPORT_CODES:
                self.attempt = 0
                return float(self.config.collection_interval_seconds)
            delay = self._failure_delay(exc)
            self.attempt = min(self.attempt + 1, 31)
            return delay
        except ClientContractError:
            self._log_throttled("payload_incompatible")
            delay = self._failure_delay(
                DeviceTransportError("payload_incompatible")
            )
            self.attempt = min(self.attempt + 1, 31)
            return delay
        except Exception:
            self._log_throttled("collection_failed")
            delay = self._failure_delay(
                DeviceTransportError("collection_failed")
            )
            self.attempt = min(self.attempt + 1, 31)
            return delay

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        stop = stop_event or threading.Event()
        while not stop.is_set():
            delay = self.run_once()
            if stop.wait(delay):
                return

    def _failure_delay(self, error: DeviceTransportError) -> float:
        if error.retry_after_seconds is not None:
            return min(300.0, max(1.0, error.retry_after_seconds))
        delay = retry_delay_seconds(
            self.attempt,
            jitter_fraction=self.random_value(),
        )
        if error.code in SLOW_RETRY_CODES:
            delay = max(30.0, delay)
        return min(300.0, max(1.0, delay))

    def _log_throttled(self, code: str) -> None:
        now = self.monotonic()
        if code != self._last_log_code or now - self._last_log_at >= 60.0:
            self.logger("device_v2 transport: " + code)
            self._last_log_code = code
            self._last_log_at = now


def create_device_v2_runner(
    config: ClientV2Config,
    *,
    collect_stats: Callable[[], Mapping[str, Any]],
    apply_monitors: Callable[[list[dict[str, Any]]], None],
    connection_factory: Callable[
        [ClientV2Config, ssl.SSLContext | None], Any
    ]
    | None = None,
    random_value: Callable[[], float] = random.random,
    logger: Callable[[str], None] = print,
    monotonic: Callable[[], float] = time.monotonic,
) -> DeviceV2Runner:
    client = DeviceHTTPSClient(
        config,
        connection_factory=connection_factory,
    )
    return DeviceV2Runner(
        config=config,
        collect_stats=collect_stats,
        apply_monitors=apply_monitors,
        client=client,
        cache=MonitorCache(),
        random_value=random_value,
        logger=logger,
        monotonic=monotonic,
    )


def install_monitor_definitions(
    monitor_state: dict[str, dict[str, Any]],
    monitors: list[dict[str, Any]],
    *,
    thread_target: Callable[..., None],
    thread_factory: Callable[..., threading.Thread] = threading.Thread,
) -> None:
    next_state: dict[str, dict[str, Any]] = {}
    workers: list[threading.Thread] = []
    for monitor in monitors:
        name = monitor["name"]
        previous = monitor_state.get(name)
        if (
            previous is not None
            and previous.get("type") == monitor["type"]
            and previous.get("host") == monitor["host"]
            and previous.get("_interval") == monitor["interval"]
        ):
            next_state[name] = previous
            continue
        generation = next(_MONITOR_GENERATIONS)
        next_state[name] = {
            "type": monitor["type"],
            "host": monitor["host"],
            "latency": 0,
            "_interval": monitor["interval"],
            "_generation": generation,
        }
        worker = thread_factory(
            target=thread_target,
            kwargs={
                "name": name,
                "host": monitor["host"],
                "interval": monitor["interval"],
                "type": monitor["type"],
                "generation": generation,
            },
        )
        worker.daemon = True
        workers.append(worker)
    monitor_state.clear()
    monitor_state.update(next_state)
    for worker in workers:
        worker.start()
