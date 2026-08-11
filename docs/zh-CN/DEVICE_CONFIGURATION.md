# 设备配置编写指南

[English](../DEVICE_CONFIGURATION.md) · [配置总览](CONFIGURATION.md)

Device v2 将传输凭据与设备展示信息分离。运维人员通过配置文件维护设备名称和接入地址，而不是接受 Client 上报的主机名。

## 名称与地址的权威来源

设备选择器和首页名称以 Device Registry 的 `devices[].display_name` 为准，Client 上报的名称不能覆盖该值。生产环境请使用稳定名称（如 `GK50`），不要在展示名称中保留 `Preview` 等临时部署后缀。每台 Client 在 `client-v2.json` 中独立维护服务端接入地址与 HTTPS 端口，例如 `https://status.example.invalid:21443`。

生产路径示例（不是仓库内文件）：

| 用途 | 宿主机路径 | 容器路径 | 挂载方式 |
| --- | --- | --- | --- |
| Device Registry | `/etc/hermesstatus/device-v2/devices.json` | `/etc/hermesstatus/devices.json` | 只读 |
| Credential 目录 | `/etc/hermesstatus/device-v2/credentials.d` | `/etc/hermesstatus/credentials.d` | 只读 |
| Legacy 映射 | `/etc/hermesstatus/device-v2/legacy-device-mapping.json` | `/etc/hermesstatus/legacy-device-mapping.json` | 只读 |
| Client 配置 | `/etc/hermesstatus/device-v2/client-v2.json` | `/etc/hermesstatus/client-v2.json` | 只读 |
| 设备 Token | `/etc/hermesstatus/device-v2/secrets/gk50.token` | `/run/secrets/hermesstatus-device-token` | 只读 |

## 服务端与 Registry 文件

以[Registry 示例](../../config/examples/device-registry.example.json)为模板；仅存在 Legacy TCP Client 时才参考[映射示例](../../config/examples/legacy-device-mapping.example.json)。映射不用于 Device v2 的命名或授权。

```json
{
  "id": "gk50",
  "display_name": "GK50",
  "enabled": true,
  "order": 10,
  "ingestion": {"mode": "device_v2", "active_protocol": "device_v2", "cutover_not_after": null}
}
```

Registry 不保存 token；对应 credential 文件只保存 SHA-256 digest。

## Client 文件

每个 Client 独立维护 `client-v2.json`。`server.url` 填写服务端接入地址与 HTTPS 端口；`device.name` 仅用于身份提示，浏览器显示名仍以服务端配置为准。

```json
{
  "version": 1,
  "server": {
    "url": "https://status.example.invalid:21443",
    "verify_tls": true,
    "ca_file": "/run/secrets/hermesstatus-ca.crt",
    "connect_timeout_seconds": 10,
    "read_timeout_seconds": 30
  },
  "device": {
    "id": "gk50",
    "name": "GK50 主机",
    "fqdn": null,
    "token_file": "/run/secrets/hermesstatus-device-token"
  },
  "collection": {"interval_seconds": 60},
  "hardware": {
    "smart_devices": [
      {"path": "/dev/sda", "type": null, "label": "data-disk-a"},
      {"path": "/dev/sdb", "type": "sat", "label": "data-disk-b"}
    ],
    "primary_smart_device": "/dev/sda",
    "filesystem_probes": [
      {"mountpoint": "/data", "probe_path": "/host-storage/data"}
    ]
  }
}
```

`url` 必须匹配 TLS 证书的名称或 IP SAN。Token 文件应归 Client 运行用户所有，权限只能是 `0400` 或 `0600`。

## Compose 挂载映射

Server 覆盖配置：

```yaml
services:
  serverstatus-server:
    volumes:
      - /etc/hermesstatus/device-v2/devices.json:/etc/hermesstatus/devices.json:ro
      - /etc/hermesstatus/device-v2/credentials.d:/etc/hermesstatus/credentials.d:ro
      - /etc/hermesstatus/device-v2/legacy-device-mapping.json:/etc/hermesstatus/legacy-device-mapping.json:ro
```

每个 Client 使用独立配置、Token、CA、状态目录，以及只允许其观测的硬件路径：

```yaml
services:
  serverstatus-client:
    environment:
      HERMESSTATUS_CONFIG_FILE: /etc/hermesstatus/client-v2.json
      # JSON 多盘 allowlist 为权威时保持为空，避免被覆盖。
      SMART_DEVICE: ""
    devices: !override
      - /dev/sda:/dev/sda:r
      - /dev/sdb:/dev/sdb:r
    volumes:
      - /etc/hermesstatus/device-v2/client-v2.json:/etc/hermesstatus/client-v2.json:ro
      - /etc/hermesstatus/device-v2/secrets/gk50.token:/run/secrets/hermesstatus-device-token:ro
      - /etc/hermesstatus/device-v2/ca.crt:/run/secrets/hermesstatus-ca.crt:ro
      - /var/lib/hermesstatus/device-v2/gk50:/var/lib/serverstatus-client
      - /srv/example-data:/host-storage/data:ro
```

基础 Client Compose 为非 privileged，且不映射宿主机块设备，因此不会假设存在 `/dev/sda`。受审计的覆盖文件会添加 `SYS_RAWIO` 并使用 `devices: !override`，使映射路径与 JSON allowlist 精确一致。不得挂载完整 `/dev`、使用 `privileged`、增加 `SYS_ADMIN`，也不能仅为文件系统容量挂载宿主机根目录。每个文件系统 probe 都需要单独的窄范围只读挂载；它只会经由 `findmnt` 和 `statvfs` 采样，绝不遍历文件。

`smart_devices` 中的 `label` 是采集器配置元数据，不承诺持久化或渲染。设备、型号、挂载点和文件系统观测数据同样不能用于标识或认证 Client。

重启前验证服务端输入：

```bash
serverstatus --validate-device-config \
  --device-registry /etc/hermesstatus/devices.json \
  --device-credentials /etc/hermesstatus/credentials.d \
  --legacy-device-mapping /etc/hermesstatus/legacy-device-mapping.json
```

不得提交生产配置、token、digest 文件、私有 CA 或私有地址。

## 只读诊断与构建溯源

设备信息对话框为只读。它可以显示 Device ID、配置的显示名、启用/接入模式/协议状态、安全的采集时间、系统身份、已配置 EasyTier expectation 状态以及 Server/Client 构建溯源；绝不能显示 token、digest、credential 或 Registry 路径、源地址证据、私有 CA 或认证头。

环境标签由 Server 部署提供，例如 `HERMESSTATUS_DEPLOYMENT_ENV=preview`，不能从当前 Preview 端口 21443 推断。镜像构建时注入版本、revision 和构建时间。候选资格验证期间，应比对完整的 Server/Client revision 与相应的 `org.opencontainers.image.revision` label。

## EasyTier expectation 示例

可选 expectation 与权威展示名称保存在 Registry 文件中（例如宿主机
`/etc/hermesstatus/device-v2/devices.json`），Server Compose 将它只读挂载为
`/etc/hermesstatus/devices.json`。它不应写入 `client-v2.json`，也不会改变 Client
的 Server URL、端口、认证或 device ID。

```json
{
  "id": "gk50",
  "display_name": "GK50",
  "easytier_expectation": {
    "administrative_role": "site_router",
    "network_name": "home-404",
    "overlay_ipv4": "10.0.0.1",
    "proxy_cidrs": ["10.0.0.0/24"]
  }
}
```

真实记录仍须保留既有必填 Registry 字段；上例只说明新增的可选块。Client EasyTier
配置独立挂载，只允许本地 CLI 路径、loopback RPC portal、timeout、interval 和 enabled。
