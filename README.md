# HermesStatus 2.3 Preview

[English](README_EN.md) · [中文文档](docs/zh-CN/README.md) · [English docs](docs/README.md)

HermesStatus 是自托管的当前状态面板。Go Server 接收 Client 上报并提供 WebUI 与状态 API；Python Client 采集主机、硬件/SMART、Docker、Hermes、可选 Lucky 与可选 EasyTier 健康摘要。

## 当前功能

- 设备名称由 Device Registry 配置文件维护，不会被 Client 主机名覆盖；生产环境应使用稳定名称（如 `GK50`），不要将 Preview、临时环境等字样写入展示名称。每台 Client 的接入 IP 和端口由独立 Client 配置文件维护。
- 主页首行展示 CPU、内存、磁盘容量、EasyTier 远端节点数与 EasyTier 流量统计；硬件状态区域展示 SMART、读写量、通电时间、系统运行时间、物理机操作系统、Docker、Lucky 与 EasyTier 运行状态/版本。状态与版本采用“正常（版本）”的紧凑展示；EasyTier 流量以一位小数、`接收 / 发送 / 转发`格式按 B、KB、MB、GB 等单位自动换算并保持单行。
- Docker 页面展示容器数量、名称、镜像、状态与端口摘要。
- 主页同时展示已配置 Hermes Profile 的网关、运行状态、模型/提供商与用量快照；Profile 表头显示统一 Agent 版本与配置数量（例如 `Agent版本: 0.19.0，3个配置`）。
- Lucky 页面在显式启用后展示版本、DDNS、Web 服务、端口转发和证书摘要。
- EasyTier 页面在显式启用后先以独立状态模块显示每项只读采集命令，再展示节点、Configured vs Observed、Peer、Route、Connector 与流量的严格白名单投影。零远端节点是健康的“未观察到”状态：直连、中继和 IPv6 UDP Direct 不会被误报为 0 或 false。
- 支持 Legacy TCP Agent；可选 Device v2 使用 Registry、digest credential 与受 HTTPS 代理保护的上报端点。

网络流量、网络吞吐、三网/运营商延迟探测不是 HermesStatus 面板功能。

## 架构

```text
主机 / hwmon / SMART / Docker / Hermes / Lucky / EasyTier
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

## SMART 最小权限

单盘 SMART 采集需要设备 ioctl。不要为了读取 SMART 使用 `privileged` 或挂载完整 `/dev`。已确认设备为 `/dev/sda` 时，Client Compose 使用：

```yaml
cap_add:
  - SYS_RAWIO
devices:
  - /dev/sda:/dev/sda:r
environment:
  SMART_DEVICE: /dev/sda
```

这段配置应替换而非叠加在 `docker-compose-client.yml` 中遗留的宽泛设置上：添加 capability 和单设备映射前，设置 `CLIENT_PRIVILEGED=false`，并删除 `/dev:/dev:ro` 卷挂载。保留这些旧默认值就不是最小权限部署。

保留只读根文件系统与 `no-new-privileges`。其他磁盘、RAID 或 NVMe 主机必须先确认具体设备再授权。

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
- [设备配置编写指南](docs/zh-CN/DEVICE_CONFIGURATION.md)

常用验证：

```bash
(cd server && go test ./...)
(cd clients && python3 -m unittest discover)
(cd scripts/tests && python3 -m unittest discover)
```

`2.3-preview` 是 2.3 的唯一集成与 21443 staging 分支；它不会自动推进到 `2.0`。当前仅以 GK50 的 zero-peer 数据完成真实采集验证；双站点 Synology、IPv6 UDP Direct、TCP fallback、192.168.88.0/24 与真实 Direct/Relay 行为仍待真实资格验证。Synthetic fixtures 只用于预览状态验证，绝不表示真实网络已验证。

不得提交真实 token、密码、credential、私有地址或生产配置。

## 许可

[MIT License](LICENSE)
