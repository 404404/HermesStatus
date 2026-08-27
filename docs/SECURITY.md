# Security

HermesStatus is intentionally read-only. Its safety model is based on explicit identity, narrow collection allowlists, validation at every boundary and least-privilege deployment.

## Identity and secrets

Device v2 uses TLS and a per-device token. The Server stores only token digests. Clients read tokens and CA material from root-owned files mounted read-only. Do not log, print, hash for reporting, commit or place credentials in command lines, environment values, fixtures, stats documents or UI text.

## Collection boundaries

Collectors use fixed source allowlists and argv arrays. They reject arbitrary commands, remote URLs, redirects, raw configuration, credentials and sensitive EasyTier objects. Lucky is limited to loopback endpoints; EasyTier is limited to a configured loopback RPC and read-only CLI queries. No management, credential, routing, port-forward, logging or service-control commands are in the runtime allowlist.

## Host privileges

Do not use privileged containers, `SYS_ADMIN`, a Docker socket, whole `/dev` or the host root. Grant only explicit SMART device mappings and `SYS_RAWIO` where needed. Filesystem and DSM probes use fixed narrow read-only mounts. A controlled deployment helper must offer only fixed subcommands and paths; it must not become generic `sudo`, Docker or shell access.

## Data handling

Server validation bounds counts, strings, counters, timestamps, CIDRs and enums. Unknown sensitive fields and raw objects are discarded. HTML uses safe escaping and tests cover malicious values. Persistence applies accepted updates atomically and refuses stale/conflicting mutation.

## Reporting vulnerabilities

Do not include secrets or live infrastructure identifiers in an issue. Provide the smallest reproducible, sanitized description through the repository's private security contact or maintainer channel.

## UniFi remote-observation boundary

UniFi V1 has no generic `run_remote(command)` interface. Profiles reference
only code-side symbolic source IDs, and the Client invokes a fixed bundled
read-only SSH script with argv arrays, a bounded timeout, `setsid --wait`,
keyboard-interactive authentication, and `StrictHostKeyChecking=yes`. The
password is read only from a validated protected file by a short-lived local
askpass helper; it is not written to argv, logs, stats, fixtures, UI, image
labels, or environment values. Host-key failure is a safe telemetry error, not
permission to accept a replacement key. The Client does not install keys, scan
networks, modify UniFi configuration, read configuration databases, or execute
fan/PWM/storage control commands.
