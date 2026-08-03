# HermesStatus 2.0

[English](README_EN.md) · [中文文档](docs/zh-CN/README.md) · [English docs](docs/README.md)

HermesStatus 是自托管的当前状态面板。Go Server 接收 Client 上报并提供 WebUI 与状态 API；Python Client 采集主机、硬件/SMART、Docker、Hermes 与可选 Lucky 数据。

## 当前功能

- 主页展示设备状态、CPU、内存、磁盘容量、主机/CPU 身份、温度与 SMART。
- Docker 页面展示容器数量、名称、镜像、状态与端口摘要。
- Hermes 页面展示已配置 Profile 的网关、运行状态、模型/提供商与用量快照。
- Lucky 页面在显式启用后展示版本、DDNS、Web 服务、端口转发和证书摘要。
- 支持 Legacy TCP Agent；可选 Device v2 使用 Registry、digest credential 与受 HTTPS 代理保护的上报端点。

网络流量、网络吞吐、三网/运营商延迟探测不是 HermesStatus 面板功能。

## 架构

```text
主机 / hwmon / SMART / Docker / Hermes / Lucky
                     ↓
                Python Client
                     ↓
    Legacy TCP Agent 或受认证 HTTPS Device v2 上报
                     ↓
                  Go Server
                     ↓
      /json/stats.json · /api/health · WebUI
```

浏览器只读取 `/json/stats.json`。Server 不挂载 Docker socket，也不读取 Hermes 或 Lucky 秘密；这些高信任采集工作仅存在于 Client。

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

常用验证：

```bash
go test ./...
(cd clients && python3 -m unittest discover)
(cd scripts/tests && python3 -m unittest discover)
```

不得提交真实 token、密码、credential、私有地址或生产配置。

## 许可

[MIT License](LICENSE)
