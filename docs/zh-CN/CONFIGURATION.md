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

## 硬件采集

硬件详情是有边界的可选观测数据。`hardware.storage` 将物理磁盘与文件系统分开：一个文件系统可以解析到一块、多块或没有已上报的物理盘。这样可支持普通分区、LVM、MD RAID、device mapper 与 Btrfs/EXT4 存储栈，而不会猜测逻辑卷就是磁盘。

Device v2 优先在 `client-v2.json` 中使用可选 `hardware` 对象：

```json
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
```

`smart_devices` 是 0–64 个 Client 容器内可见 `/dev/*` 路径的显式 allowlist。显式空数组会停用 SMART 探测、仅保留安全的拓扑库存，并不代表采集失败。可选 `type` 是有长度限制的 smartctl 设备类型，如 `sat`、`scsi` 或 `nvme`，不是 shell 片段；`label` 是采集器配置元数据，不承诺作为持久化或 UI 展示字段。`primary_smart_device` 可选，在观察到多块盘时选择兼容的单盘 SMART 字段来源。未设置时不会任意取第一块盘，详细的 `storage.physical_disks` 才是权威数据。

`filesystem_probes` 是最多 128 个显式配置的绝对展示 `mountpoint`（最多 512 个字符）与容器 `probe_path` 对。展示挂载点会原样保留，包括合法的重复空白；probe 路径必须是目标宿主机文件系统的只读挂载。Client 只运行 `findmnt` 和 `statvfs`，不会遍历或上传目录内容。bind mount source 会归一化为安全的 `/dev/*` 组件；非设备 source 会被省略而不会上报为端点。只有在能安全证明全部成员时才关联 Btrfs 后端磁盘，否则明确保留未知关系。伪文件系统或不可用 probe 会明确显示不可用，不会被误报为宿主机存储。

配置优先级为 CLI、环境变量、JSON 文件、默认值。环境变量可使用 `HERMESSTATUS_SMART_DEVICES` / `SMART_DEVICES`、`HERMESSTATUS_PRIMARY_SMART_DEVICE` / `PRIMARY_SMART_DEVICE` 与 `HERMESSTATUS_FILESYSTEM_PROBES` / `FILESYSTEM_PROBES`，其中 JSON 值采用 JSON 数组。Legacy `SMART_DEVICE` 仍保留为最低优先级的单设备形式。镜像默认的 `SMART_DEVICE=auto` 是自动发现哨兵，不会覆盖 JSON 的 `smart_devices`（包括有意设置的空数组）。若希望 JSON 多盘 allowlist 为权威，不要在 Compose 覆盖中设置非空的 Legacy `SMART_DEVICE`。

为兼容性保留 `auto`，但它只能发现 Client 容器中已经可见的块设备；不会授予设备权限、修改 cgroup、读取不可见的宿主机路径或扩大 `/dev` 访问范围。数据与安全合同见[硬件监控设计](../design/HARDWARE_MONITORING.md)，Compose 挂载见[设备配置指南](DEVICE_CONFIGURATION.md)。

## Hermes 与 Lucky

`HERMES_EXPORT_CONFIG` 指向 JSON 或 YAML exporter 配置，用于定义 Hermes 根目录和需要检查的 Profile。exporter 通过只读挂载读取配置与状态，并在 Client 状态目录写入脱敏快照。

Lucky 采集为显式启用，默认本地地址为
`https://127.0.0.1:16601`；Collector 只接受回环 HTTP(S) URL。设置
`LUCKY_ENABLED=true` 后，如安装确实需要认证，使用
`LUCKY_AUTH_MODE=open_token` 或 `admin_token` 并通过受保护的
`LUCKY_TOKEN_FILE` 读取 token，不能将 token 写入 Compose 文件。若本地 API
不要求认证，设置 `LUCKY_AUTH_MODE=none` 且不设置 `LUCKY_TOKEN_FILE`。

HTTPS Lucky API 应保持 `LUCKY_VERIFY_TLS=true`。仅当本机管理的、严格回环的
Lucky endpoint 证书无法验证时，才可显式设置 `LUCKY_VERIFY_TLS=false`；这不会
允许远程 Lucky URL，Collector 也绝不会自动降级 TLS 验证。

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

设备名称、IP/端口、文件路径与 Compose 挂载的完整操作见[设备配置编写指南](DEVICE_CONFIGURATION.md)。浏览器显示名称以 Device Registry 的 `display_name` 为准；Client URL 由运维配置维护。

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

## 可选 EasyTier expectation

仅当运维人员需要比较诊断时，才在现有 Registry 的设备记录中添加 expectation。
它是可选项，不能创建设备、认证 Client 或选择凭据：

```json
"easytier_expectation": {
  "administrative_role": "site_router",
  "network_name": "home-404",
  "overlay_ipv4": "10.0.0.1",
  "proxy_cidrs": ["10.0.0.0/24"]
}
```

允许的角色为 `site_router`、`endpoint`、`bootstrap_listener`、
`relay_capable` 与 `observer`；Overlay 和 Proxy 值必须是内部地址。只填写
经确认的期望值；尚未观察到数据不是故障，会显示为 `not_observable`。
