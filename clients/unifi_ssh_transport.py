"""Fixed, read-only OpenSSH transport for a configured UniFi target."""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
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
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or not owner_ok or info.st_mode & 0o077:
        code = "host_key_configuration" if field == "known_hosts_file" else field + "_invalid"
        raise TransportError(code)
    if private and stat.S_IMODE(info.st_mode) not in (0o400, 0o600):
        raise TransportError(field + "_invalid")

def _askpass(credential_file):
    _validate_file(credential_file, "credential_file", private=True)
    fd, name = tempfile.mkstemp(prefix="hermesstatus-unifi-askpass-", text=True)
    try:
        escaped = credential_file.replace("'", "'\"'\"'")
        os.write(fd, ("#!/bin/sh\nexec /bin/cat '" + escaped + "'\n").encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(name, 0o700)
    return name

def _run_fixed(remote_script, config):
    # known_hosts is public trust metadata, not a credential. In the
    # container the collector runs as root while the administrator-managed
    # source may remain owned by the host user; keep it strictly private
    # (no group/other bits) and require a regular non-symlink file.
    _validate_file(config.known_hosts_file, "known_hosts_file", allow_root_readable=True)
    askpass = _askpass(config.credential_file)
    env = os.environ.copy()
    env.update({"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force", "DISPLAY": "hermesstatus-unifi"})
    command = ["setsid", "--wait", "ssh", "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + config.known_hosts_file, "-o", "KbdInteractiveAuthentication=yes", "-o", "PasswordAuthentication=no", "-o", "PreferredAuthentications=keyboard-interactive", "-o", "PubkeyAuthentication=no", "-o", "ConnectTimeout=" + str(config.connect_timeout_seconds), "-p", str(config.port), config.username + "@" + config.host, remote_script]
    try:
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=config.connect_timeout_seconds + 15, env=env, check=False)
    except subprocess.TimeoutExpired as exc:
        raise TransportError("ssh_timeout") from exc
    except OSError as exc:
        raise TransportError("ssh_transport_failure") from exc
    finally:
        try: os.unlink(askpass)
        except OSError: pass
    if completed.returncode:
        lowered = completed.stderr.lower()
        if "host key verification failed" in lowered:
            raise TransportError("host_key_failure")
        if "permission denied" in lowered or ("userauth_kbdint" in lowered and "no info_req_seen" in lowered):
            raise TransportError("ssh_auth_failure")
        raise TransportError("ssh_transport_failure")
    if len(completed.stdout.encode("utf-8", "ignore")) > 32768:
        raise TransportError("ssh_output_too_large")
    return completed.stdout

def collect_core(config):
    return _run_fixed(REMOTE_CORE_SCRIPT, config)

def collect_diagnostics(config):
    return _run_fixed(REMOTE_DIAGNOSTICS_SCRIPT, config)
