# Security

[中文](zh-CN/SECURITY.md) · [Documentation index](README.md)

## Trust boundaries

The Server is a status projector. It does not mount the Docker socket and does
not read Hermes or Lucky host secrets. The Client is the high-trust component:
it reads host files, optional hardware devices, the Docker socket, and selected
Hermes/Lucky inputs before sending a sanitized extension to the Server.

Deploy the Client only on a reviewed host. A read-only Docker socket bind does
not make the Docker API read-only; the collector is constrained in code to the
container-list request, but socket access remains sensitive.

## Secrets

Keep `ADMIN_TOKEN`, Agent passwords, Bearer credentials, Lucky tokens, private
addresses, and production configuration outside Git. Use protected files or a
secret mount. Do not put secret values in Compose files, log output, screenshots,
issues, pull requests, or documentation.

The Server stores v2 device credential digests, not raw tokens. Credential
records support current and next slots for rotation. A Client sends its raw
Bearer token only to the trusted HTTPS ingress route.

## EasyTier collector boundary

EasyTier monitoring permits exactly `node info`, `peer list`, `route list`,
`connector list`, and `stats show`, through a loopback-only RPC portal. It uses
an absolute executable and argv-based subprocess invocation with no shell. The
projection excludes configuration, keys, credentials, RPC addresses, STUN data,
public/listener endpoints, raw JSON, and stderr. Unknown payload fields are
rejected by the Server before persistence and UI projection.

## Device v2 ingress

The endpoint is disabled by default. When enabled, require HTTPS at the proxy,
trust forwarding headers only from explicitly configured proxy addresses, and
replace untrusted external forwarding headers. Restrict the proxy to the exact
POST route. The Server rejects invalid content type, oversized bodies, duplicate
identity headers, invalid credentials, disabled devices, inactive protocol
ownership, replay conflicts, and rate-limit excess.

## Safe observability

Use `/api/health` and sanitized `/json/stats.json` for diagnosis. Do not expose
raw SMART output, Docker API responses, Hermes configuration, `.env` files, or
authentication headers. The dashboard may report stale or unavailable data;
that is safer than inventing a healthy value.
