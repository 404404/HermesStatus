# 配置

[English](../CONFIGURATION.md) · [文档目录](README.md)

## 服务端配置

服务端读取包含 `servers`、可选 `monitors` 和可选 `sslcerts` 的 JSON 文档。节点记录至少需要唯一 `username`、显示名 `name`、`type`、`host`、`location`、`password` 与 `monthstart`。不得提交生产配置或真实密码。

| 变量 | 用途 |
| --- | --- |
| `CONFIG_PATH` | 服务端 JSON 配置。 |
| `STATS_PATH` | 可写的当前状态持久化文件。 |
| `HTTP_ADDR` | WebUI 与 HTTP API 监听地址。 |
| `AGENT_ADDR` | Legacy TCP Agent 监听地址。 |
| `ADMIN_TOKEN` | 启用需认证的管理 API。 |
| `WEB_DIR` | WebUI 静态文件目录。 |

未设置 `ADMIN_TOKEN` 时，公开状态端点仍可读取，写入配置的管理 API 会被禁用。

## 客户端配置

Legacy TCP Client 需要 `SERVER`、`SERVERSTATUS_USER`、`PASSWORD` 与 `PORT`。推荐使用 `SERVERSTATUS_USER`；`USER` 只用于兼容，不应意外继承宿主机用户变量。

主机采集常用变量包括 `HWMON_ROOT`、`SMART_DEVICE`、`DOCKER_SOCKET`、`HARDWARE_INTERVAL`、`DOCKER_INTERVAL` 与 `CLIENT_STATUS_DIR`。

## Hermes 与 Lucky

`HERMES_EXPORT_CONFIG` 指向 JSON 或 YAML exporter 配置，用于定义 Hermes 根目录和需要检查的 Profile。exporter 通过只读挂载读取配置与状态，并在 Client 状态目录写入脱敏快照。

Lucky 采集为显式启用：设置 `LUCKY_ENABLED=true`、提供 `LUCKY_BASE_URL`，并通过 `LUCKY_TOKEN_FILE` 读取 token，不要将 token 写入 Compose 文件。HTTPS Lucky API 应保持 `LUCKY_VERIFY_TLS=true`。

## EasyTier 监控

EasyTier 监控默认关闭，必须显式启用。配置优先级从高到低为 EasyTier CLI 参数、环境变量、由 `EASYTIER_CONFIG_FILE` 指定的只读 JSON 文件、默认值。

| 配置 | 默认值 | 约束 |
| --- | --- | --- |
| `EASYTIER_ENABLED` | `false` | 必须显式启用。 |
| `EASYTIER_CLI_PATH` | `/usr/local/bin/easytier-cli` | 必须是绝对路径、可执行普通文件；拒绝符号链接。 |
| `EASYTIER_RPC_PORTAL` | `127.0.0.1:15888` | 仅接受 `127.0.0.1:15888` 或 `[::1]:15888`。 |
| `EASYTIER_TIMEOUT_SECONDS` | `5` | 1 到 30 的整数。 |
| `EASYTIER_INTERVAL_SECONDS` | `30` | 5 到 3600 的整数。 |

JSON 文件只允许 `enabled`、`cli_path`、`rpc_portal`、`timeout_seconds` 与 `interval_seconds`，且必须为组和其他用户不可写的普通文件。只读挂载 CLI 二进制到 Client；不要挂载 EasyTier 配置、密钥，或配置非回环 RPC portal。

## Device v2 配置

Device v2 需要四个由操作员管理的路径：

| 变量 | 内容 |
| --- | --- |
| `DEVICE_REGISTRY_PATH` | 只读、权威设备 Registry。 |
| `HERMESSTATUS_DEVICE_CREDENTIALS_DIR` | 每台 v2 设备一份仅含 digest 的 credential 文件。 |
| `LEGACY_DEVICE_MAPPING_PATH` | 显式 Legacy 用户名到设备 ID 映射。 |
| `PERSISTENCE_PATH` | 可写 v2 运行状态。 |

只有在设置 `HERMESSTATUS_DEVICE_ENDPOINT_ENABLED=true` 并配置明确可信代理边界时才启用端点。启动前执行：

```bash
serverstatus --validate-device-config \
  --device-registry /absolute/path/devices.json \
  --device-credentials /absolute/path/credentials.d \
  --legacy-device-mapping /absolute/path/legacy-device-mapping.json
```
