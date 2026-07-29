# HermesStatus 2.2 Multi-Device Deployment Plan

Status: Stage A contract candidate implemented locally; no production build,
runtime activation, or deployment is authorized by this document.

## 1. Entry gates

Contract/mock implementation may start only after approval of:

- JSON registry schema and device ID rules;
- HTTPS envelope and common ingestion adapter model;
- per-device token digest source and rotation ownership;
- `servers[]` minimal evolution and FQDN-null browser policy;
- persistence version/migration;
- selector/routes/default fallback;
- legacy compatibility window.

Production deployment additionally requires named operational ownership for
HTTPS termination, DNS, certificate/CA renewal, credential provisioning,
backups, rollback, and legacy retirement.

## 2. Implementation stages

### Stage A: contracts and fixtures

- strict registry, credential, legacy mapping, envelope/response, Client config,
  stats, and persistence schemas are present;
- synthetic legal/illegal single/multi-device fixtures are present;
- status/identity/protocol and write-ownership enums are frozen;
- pure parser/normalizer/projector/migration/generation tests are present with
  no runtime activation.

### Stage B: state and persistence

- re-key the existing node map by `device_id`;
- create registered `never_seen`/disabled states;
- implement registry-authoritative persistence merge and orphan retention;
- retain current domain decoders and legacy TCP tests;
- add concurrency/race coverage.

### Stage C: authentication and HTTPS adapter

- implement credential digest loader and rotation slots;
- implement the fixed HTTPS update endpoint;
- bind header/body/registry/credential identity;
- route both HTTPS and TCP adapters to one ingestion function;
- retain monitor-definition response semantics.

### Stage D: Client

- create one shared config/URL/TLS/token/retry module;
- adapt both existing Client variants;
- preserve collector/domain isolation and runtime hardening;
- keep legacy mode explicit and fail closed on partial v2 config.

### Stage E: stats and UI

- emit schema metadata and canonical fields in existing `servers[]`;
- keep all 2.1 fields/parsers;
- add selector, route parsing, localStorage fallback, and page isolation;
- keep one document, one fetch path, and one timer.

### Stage F: qualification

- run the complete matrix below;
- verify reproducible provenance and release boundary checks;
- inspect images/manifests without deploying;
- obtain security and operations approval.

## 3. Test matrix

### Client configuration and transport

| Area | Required cases |
| --- | --- |
| Sources | environment, JSON file, explicit CLI, exact CLI > env > file > default precedence |
| Required values | missing Server URL, missing ID, missing token file |
| Validation | illegal ID, illegal FQDN, URL credentials/query/fragment/path, unknown config keys |
| Secret file | missing, directory, symlink, empty, oversized, mode too broad, valid 0400/0600 |
| TLS | verify on, bad CA, SAN mismatch, expired certificate, insecure non-loopback rejection |
| Network | DNS failure/recovery, IPv4/IPv6 fallback, connect timeout, read timeout |
| HTTP | 202, 400, 401, 403, 404, 413, 415, 429, 500, redirect rejection |
| Retry | jitter/cap, no busy loop, reset after success, recovery after Server/DNS return |
| Secrecy | no token in payload, URL, process args, logs, exception, fixtures |
| Runtime | collector/report failure does not terminate main process; hardening unchanged |

### Server registry, auth, state, and persistence

| Area | Required cases |
| --- | --- |
| Registry | valid, duplicate ID, bad default, bad FQDN, limits, unknown fields, atomic invalid reload |
| Visibility | online, degraded, stale, offline, never seen, disabled, zero enabled |
| Auth | correct binding, wrong token, missing token, header/body mismatch, unknown, disabled |
| FQDN | matched, mismatch, missing, no expectation, invalid syntax |
| Isolation | two independent devices, Client A cannot update B, one device error leaves others unchanged |
| Concurrency | concurrent distinct devices, concurrent same device, old request generation, legacy duplicate connection |
| Payload | size limit, strict envelope, forbidden fields, clock skew, malformed domain isolation |
| Scale | 128 devices accepted, 129 rejected, stable `(order,id)` sorting |
| Persistence | multi-device restart, renamed/reordered registry, disable/remove/re-add, orphan retention, corrupt snapshot |
| Freshness | restored data non-online; device and domain stale independently |
| Race | full Server/ingestion/persistence tests under race detector |

### Compatibility

- 2.1 Client through explicit legacy mapping;
- 2.2 Client through HTTPS;
- old and new Clients online on different IDs;
- controlled same-ID cutover without dual writers;
- legacy Client cannot select/overwrite a new device;
- current structured and `hardware_json`/`docker_json`/`hermes_json` fixtures;
- no `device_json` and no removed retained parser;
- legacy Web hashes;
- 2.1 single-device and multi-item stats fixtures;
- rollback reader/configuration compatibility.

### Frontend

- shared secondary selector on Home/Docker/Lucky;
- URL, localStorage, default ID, stable first-enabled precedence;
- invalid/encoded/duplicate device fallback and canonical URL rewrite;
- offline and never-seen visible; disabled excluded;
- current selection preserved across stats refresh;
- removed/disabled current selection falls back;
- per-device Home/Docker/Lucky data never crosses devices;
- `not_configured`, error, stale, and empty states;
- desktop/mobile/keyboard/accessibility behavior;
- zero request on device/page switch;
- one request on manual refresh;
- exactly one auto-refresh timer;
- current XSS suite plus hostile labels/errors/hash/localStorage;
- invalid ID never enters DOM/localStorage.

### Security and release integrity

- per-device token isolation and constant-time verification;
- no secrets/auth mapping/internal full addresses in stats/browser/logs;
- registry/config/token/credential/CA mounts read-only;
- no command/config/control fields or endpoints;
- HTTP/redirect/TLS fail-closed rules;
- runtime hardening unchanged;
- build provenance contains exact source revision;
- release boundary validation and stats persistence checks pass.

## 4. Deployment stages

Deployment is a later separately authorized activity:

1. **Preflight**: back up configuration/persistence; inventory legacy mappings;
   verify DNS resolution inside a synthetic Client container; verify certificate
   SAN/chain/renewal; validate read-only mounts and image provenance.
2. **Server dark launch**: deploy registry/state/persistence support with HTTPS
   v2 endpoint disabled; compare legacy stats output.
3. **Stats/UI launch**: expose new fields and selector while Clients remain
   legacy; confirm one request/timer and all registered devices.
4. **HTTPS canary**: enable endpoint and one independently credentialed canary;
   explicitly switch that ID from legacy to v2 ownership.
5. **Incremental Clients**: migrate one device at a time and observe at least
   stale/offline/rotation/restart windows.
6. **Steady state**: confirm all enabled devices, secret-free observability,
   persistence restart, DNS/certificate renewal behavior.
7. **Legacy retirement**: later approval only, after zero usage and rollback
   window closure.

No phase changes DNS, TLS, tokens, images, and application code simultaneously.

## 5. DNS/TLS preflight

For every deployment environment:

- identify the container DNS provider and test lookup from the Client network;
- test reachable IPv4/IPv6 choices without hard-coded address pinning;
- verify Server hostname exactly matches certificate SAN;
- verify CA source is available read-only;
- prove normal certificate renewal does not require Client image rebuild;
- document reload/restart for custom CA replacement;
- verify no redirect is returned by the fixed endpoint;
- verify URL path prefix is rejected in release 1;
- verify production HTTP/insecure TLS cannot start;
- simulate DNS outage, DNS target change, Server outage, and automatic recovery;
- measure connect/read timeout and bounded jittered retry behavior.

## 6. Observability and success criteria

Secret-free signals:

- accepted/rejected reports by protocol/outcome;
- registry/credential validation health;
- per-device last-seen/status counts with safe labels;
- domain error/stale counts;
- persistence write/restore/orphan counts;
- HTTP latency/body-size/rate-limit counts;
- legacy versus v2 update counts.

Canary success:

- no cross-device state change;
- no extra browser fetch/timer;
- accepted updates and correct identity/status;
- restart restores all devices as non-online until refreshed;
- DNS/Server recovery is automatic;
- no secret in sampled logs/stats/browser/network metadata outside TLS;
- no hardening/provenance regression.

## 7. Rollback triggers

Immediate rollback triggers include:

- authentication bypass or cross-device overwrite;
- credential or private metadata leakage;
- persistence corruption/loss;
- more than one writer for a device;
- widespread inability to report after DNS/TLS change;
- unsafe retry storm;
- incompatible stats/UI regression;
- weakened runtime hardening or unverifiable image provenance.

## 8. Rollback layers

1. Stop migrating additional Clients.
2. Switch affected device ownership back only while its legacy credentials and
   mapping remain valid.
3. Restore prior reviewed Client/Server releases by immutable image reference.
4. Restore prior Server configuration and persistence snapshot when necessary.
5. Revert HTTPS/DNS/TLS changes independently through their owning systems.
6. Verify one writer per identity, current `servers[]`, extensions, freshness,
   and UI.
7. Preserve failed-state evidence without secrets for analysis.

Never use a force reset, delete the old worktree, purge historical state, or
re-enable an expired token as a rollback shortcut.

## 9. Blockers and readiness

No unresolved architectural blocker prevents review and a local Stage A
candidate commit. Stage B remains blocked on explicit approval.

The following block production implementation/rollout decisions, not schema
mocking:

- final HTTPS termination component and request-size/log-redaction ownership;
- final credential distribution/storage owner and rotation interval;
- explicit legacy compatibility/retirement duration;
- explicit custom CA policy, if any;
- operator decision on whether browser FQDN exposure remains disabled;
- persistence backup/retention owner and orphan purge policy.

The production runtime revision remains
`733b9dd498e9794ca9414bb9ec20b80116720426`, while the Stage A source base is
`868e6f995fa877cd77d2200661445d2bd31c3c0f`. This recorded drift does not change
the development base. After contract review and local commit authorization,
Stage B may begin only through a separate explicit instruction.
