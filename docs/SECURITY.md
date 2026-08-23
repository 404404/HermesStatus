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
