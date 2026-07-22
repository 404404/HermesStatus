# Security boundary

HermesStatus exposes sanitized current status, not control operations. The Server has no Docker Socket and no Hermes secret access. Host, SMART, Docker, and Hermes collection occurs in the Client/Exporter; only structured fields cross TCP to the Server.

Do not commit or report private IPs, SSH identities, API keys, bearer tokens, passwords, `.env` contents, raw Hermes configuration, device serials, Docker Socket responses, raw `smartctl` output, stats snapshots, or logs containing those values.

CI uses read-only repository permissions, synthetic variables, mocks/fixtures, and image builds without registry login or push. It never connects to production, Docker Socket, SMART hardware, or a real Hermes API. The blocking repository scan rejects tracked environment/private-key files and common credential forms; GitHub secret scanning should remain enabled as defense in depth.

The Client's privileged/device and Docker Socket access is a known trust boundary. Deploy it only on the intended host with reviewed mounts. The application does not provide RBAC, multi-user isolation, container controls, or Hermes execution controls.

The runtime hardening baseline uses read-only root filesystems, bounded `/tmp` tmpfs mounts, and `no-new-privileges` for both containers. The Server configuration mount is read-only. See [Runtime Permission Hardening](RUNTIME_HARDENING.md) for the evidence matrix, failed capability-drop test, and retained Client risks.
