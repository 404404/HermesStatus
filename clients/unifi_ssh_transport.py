"""Fixed, read-only OpenSSH transport for a configured UniFi target."""
from __future__ import annotations

import os
import selectors
import signal
import stat
import subprocess
import time
from pathlib import Path
from unifi_source_registry import REMOTE_CORE_SCRIPT, REMOTE_DIAGNOSTICS_SCRIPT

class TransportError(RuntimeError):
    pass

def _validate_file(path, field, private=False, allow_root_readable=False):
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        code = "host_key_configuration" if field == "known_hosts_file" else field + "_unavailable"
        raise TransportError(code) from exc
    owner_ok = info.st_uid == os.geteuid() or (allow_root_readable and os.geteuid() == 0)
    disallowed_permissions = 0o022 if field == "known_hosts_file" else 0o077
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or not owner_ok or info.st_mode & disallowed_permissions:
        code = "host_key_configuration" if field == "known_hosts_file" else field + "_invalid"
        raise TransportError(code)
    if private and stat.S_IMODE(info.st_mode) not in (0o400, 0o600):
        raise TransportError(field + "_invalid")

ASKPASS_PATH = "/app/unifi_askpass.py"

def _askpass(credential_file):
    _validate_file(credential_file, "credential_file", private=True)
    return ASKPASS_PATH


def _run_bounded(command, *, env, timeout):
    """Run a fixed command while bounding both streams during execution."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        env=env,
        start_new_session=True,
        close_fds=True,
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None and process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportError("ssh_timeout")
            events = selector.select(min(remaining, 0.25))
            if not events:
                continue
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                stream = streams[key.data]
                stream.extend(chunk)
                if len(stream) > 32768:
                    raise TransportError("ssh_output_too_large")
        returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
    except (TransportError, OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise
    finally:
        selector.close()
        for stream in (process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass
    return subprocess.CompletedProcess(
        command,
        returncode,
        stdout=bytes(streams["stdout"]).decode("utf-8", "replace"),
        stderr=bytes(streams["stderr"]).decode("utf-8", "replace"),
    )

def _run_fixed(remote_script, config):
    # known_hosts is public trust metadata, not a credential. In the
    # container the collector runs as root while the administrator-managed
    # source may remain owned by the host user; keep it strictly private
    # (no group/other bits) and require a regular non-symlink file.
    _validate_file(config.known_hosts_file, "known_hosts_file", allow_root_readable=True)
    askpass = _askpass(config.credential_file)
    env = os.environ.copy()
    env.update({
        "SSH_ASKPASS": askpass,
        "SSH_ASKPASS_REQUIRE": "force",
        "DISPLAY": "hermesstatus-unifi",
        # This is a path, never the credential value. The bundled askpass
        # executable reads the already-validated file only for the prompt.
        "HERMESSTATUS_UNIFI_CREDENTIAL_FILE": config.credential_file,
    })
    # _run_bounded() already starts the fixed command in a new session so its
    # process group can be terminated as one bounded unit.  Running an
    # additional setsid wrapper would move ssh into a different session and
    # leave it behind when the wrapper's process group is killed.
    command = ["ssh", "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + config.known_hosts_file, "-o", "KbdInteractiveAuthentication=yes", "-o", "PasswordAuthentication=no", "-o", "PreferredAuthentications=keyboard-interactive", "-o", "PubkeyAuthentication=no", "-o", "ConnectTimeout=" + str(config.connect_timeout_seconds), "-p", str(config.port), config.username + "@" + config.host, remote_script]
    try:
        completed = _run_bounded(command, env=env, timeout=config.connect_timeout_seconds + 15)
    except (subprocess.TimeoutExpired, TransportError) as exc:
        if isinstance(exc, TransportError):
            raise
        raise TransportError("ssh_timeout") from exc
    except OSError as exc:
        raise TransportError("ssh_transport_failure") from exc
    if completed.returncode:
        lowered = completed.stderr.lower()
        if "host key verification failed" in lowered:
            raise TransportError("host_key_failure")
        if "permission denied" in lowered or ("userauth_kbdint" in lowered and "no info_req_seen" in lowered):
            raise TransportError("ssh_auth_failure")
        raise TransportError("ssh_transport_failure")
    return completed.stdout

def collect_core(config):
    return _run_fixed(REMOTE_CORE_SCRIPT, config)

def collect_diagnostics(config):
    return _run_fixed(REMOTE_DIAGNOSTICS_SCRIPT, config)
