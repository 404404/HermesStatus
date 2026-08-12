# HermesStatus 2.3 Preview

[English](README_EN.md) · [中文文档](docs/zh-CN/README.md) · [English docs](docs/README.md)

HermesStatus 是自托管的当前状态面板。Go Server 接收 Client 上报并提供 WebUI 与状态 API；Python Client 采集主机、硬件/SMART、Docker、Hermes、可选 Lucky 与可选 EasyTier 健康摘要。

## 当前功能

- 设备名称由 Device Registry 配置文件维护，不会被 Client 主机名覆盖；生产环境应使用稳定名称（如 `GK50`），不要将 Preview、临时环境等字样写入展示名称。每台 Client 的接入 IP 和端口由独立 Client 配置文件维护。
- 主页首行展示 CPU、内存、磁盘容量、EasyTier 远端节点数与 EasyTier 流量统计；硬件状态区域展示 CPU 最高传感器温度、物理磁盘最高温度、SMART、读写量、通电时间、系统运行时间、物理机操作系统版本、Docker、Lucky 与 EasyTier 运行状态/版本。多盘摘要只从物理磁盘得出：温度、读写量和通电时间会标明对应设备，SMART 显示通过数与失败设备；不会把逻辑卷误当成一块物理盘。
- Hardware 标签页位于主页与 Docker 之间。它展示受限的 CPU 原始信息（型号、架构、步进、插槽/核心/线程汇总、最低/最高频率与虚拟化）、不含空闲项的短时 CPU 使用率细目（桌面端每行四项，含 I/O 等待）、内存/SWAP 与系统信息（桌面端每行三项）以及物理磁盘。独立的“文件系统/存储卷”区块已移除；经配置的只读文件系统 probe 仅用于为物理磁盘行关联分区/格式、已用/总容量和使用率条。LVM、MD RAID 与 device mapper 会列出可安全解析的后端物理磁盘；多设备 Btrfs 无法完整枚举成员时明确保留未知关系，绝不伪造单盘归属。该页不读取目录内容、磁盘序列号或 SMART 原始属性。
- Docker 页面展示容器数量、名称、镜像、状态与端口摘要。
- 主页同时展示已配置 Hermes Profile 的网关、运行状态、模型/提供商与用量快照；Profile 表头显示统一 Agent 版本与配置数量（例如 `Agent版本: 0.19.0，3个配置`）。
- Lucky 页面在显式启用后展示版本、DDNS、Web 服务、端口转发和证书摘要。
- EasyTier 页面在显式启用后先以独立状态模块显示每项只读采集命令，再展示节点、Configured vs Observed、Peer、Route、Connector 与流量的严格白名单投影。零远端节点是健康的“未观察到”状态：直连、中继和 IPv6 UDP Direct 不会被误报为 0 或 false。
- 支持 Legacy TCP Agent；可选 Device v2 使用 Registry、digest credential 与受 HTTPS 代理保护的上报端点。

网络流量、网络吞吐、三网/运营商延迟探测不是 HermesStatus 面板功能。

## 架构

```text
主机 / hwmon / SMART / 只读文件系统探针 / Docker / Hermes / Lucky / EasyTier
                     ↓
                Python Client
                     ↓
    Legacy TCP Agent 或受认证 HTTPS Device v2 上报
                     ↓
                  Go Server
                     ↓
      /json/stats.json · /api/health · WebUI
```

浏览器只读取 `/json/stats.json`。Server 不挂载 Docker socket，也不读取 Hermes 或 Lucky 秘密；这些高信任采集工作仅存在于 Client。EasyTier CLI 同样仅挂载到 Client；Server 与浏览器都不会接触 EasyTier 配置、凭据、RPC 地址或原始 CLI 输出。

## 本地启动

服务端：

```bash
docker compose --env-file /secure/path/server.env \
  -f docker-compose-server.yml up -d --build
```

客户端：

```bash
docker compose --env-file /secure/path/client.env \
  -f docker-compose-client.yml up -d --build
```

默认服务端地址为 `http://127.0.0.1:8080/`，健康检查为
`/api/health`，状态快照为 `/json/stats.json`，Legacy Agent TCP 端口为
`35601`。`SERVERSTATUS_USER` 是推荐变量；`USER` 仅用于兼容旧 Client，不能依赖宿主机的同名环境变量。

## 硬件与 SMART 最小权限

单盘 SMART 采集需要设备 ioctl。不要为了读取 SMART 使用 `privileged` 或挂载完整 `/dev`。已确认设备为 `/dev/sda` 时，Client Compose 使用：

```yaml
cap_add:
  - SYS_RAWIO
devices:
  - /dev/sda:/dev/sda:r
environment:
  SMART_DEVICE: /dev/sda
```

仓库基础 `docker-compose-client.yml` 为非 privileged，且默认不映射任何宿主机块设备，因此可在 SATA、NVMe、virtio 等主机上启动。要读取 SMART 时，使用受审计的覆盖文件显式添加 `SYS_RAWIO` 与每块已确认磁盘的只读 `devices:` 映射；`config/examples/docker-compose-client.override.example.yml` 提供完整的 Device v2 示例。

保留只读根文件系统与 `no-new-privileges`。多盘时在 Client JSON 的 `hardware.smart_devices` 中显式列出每个设备，并在 Compose 中为每个设备单独添加只读 `devices:` 映射；不要恢复 `privileged`、完整 `/dev` 挂载或 `SYS_ADMIN`。`SMART_DEVICE` 仍兼容单盘部署；`SMART_DEVICES` 是可选的 JSON 环境覆盖。仅在 Client 容器中已可见且已授权的设备范围内，`auto` 才会发现设备。

文件系统容量同样不是自动扫描宿主机：只有 `hardware.filesystem_probes` 中显式声明且以只读方式挂载到 Client 的 `probe_path` 会被 `statvfs` 检查。这样可避免容器命名空间中的容量被误报为宿主机容量，也无需挂载整个宿主机根目录。路径、设备、挂载点和型号均是经过边界校验和转义的观测数据，不能作为设备身份。

完整字段、优先级、映射和排障见[硬件监控设计](docs/design/HARDWARE_MONITORING.md)与[设备配置编写指南](docs/zh-CN/DEVICE_CONFIGURATION.md)。

## Device v2

Device v2 默认关闭。启用前准备只读 Registry、每设备仅含 SHA-256 digest 的 credential 文件、Legacy 映射（如需要）与可写运行状态文件。仅将 `POST /api/v2/device-updates` 放在固定 HTTPS 反向代理路径后；后端端口不得直接公网暴露。

启动前执行：

```bash
serverstatus --validate-device-config \
  --device-registry /absolute/path/devices.json \
  --device-credentials /absolute/path/credentials.d \
  --legacy-device-mapping /absolute/path/legacy-device-mapping.json
```

## 文档与验证

- [架构](docs/zh-CN/ARCHITECTURE.md)
- [配置](docs/zh-CN/CONFIGURATION.md)
- [部署](docs/zh-CN/DEPLOYMENT.md)
- [安全](docs/zh-CN/SECURITY.md)
- [运维](docs/zh-CN/OPERATIONS.md)
- [开发与测试](docs/zh-CN/DEVELOPMENT.md)
- [EasyTier 2.3 设计](docs/design/EASYTIER_MONITORING.md)
- [硬件监控设计](docs/design/HARDWARE_MONITORING.md)
- [设备配置编写指南](docs/zh-CN/DEVICE_CONFIGURATION.md)

常用验证：

```bash
(cd server && go test ./...)
(cd clients && python3 -m unittest discover)
(cd scripts/tests && python3 -m unittest discover)
```

`2.3-preview` 是 2.3 的唯一集成与 21443 staging 分支；它不会自动推进到 `2.0`。21443 的环境标签由部署配置提供，端口本身不定义产品环境。当前仅以 GK50 的 zero-peer 数据完成真实 EasyTier 采集验证；Synology DSM 的多盘/MD RAID/LVM/Btrfs 结构以 secret-free synthetic fixtures 完成合同资格验证，仍待真实设备资格验证。双站点 Synology、IPv6 UDP Direct、TCP fallback、未来远端私网 CIDR 与真实 Direct/Relay 行为也仍待真实资格验证。Synthetic fixtures 只用于预览状态验证，绝不表示真实网络已验证。

不得提交真实 token、密码、credential、私有地址或生产配置。

## 许可

[MIT License](LICENSE)
