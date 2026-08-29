# HermesStatus

[English](README_EN.md) · [中文文档](docs/zh-CN/README.md) · [English docs](docs/README.md)

HermesStatus 是一个自托管的多设备状态面板。Python Client 以最小权限采集主机与已配置的本地服务；Go Server 校验、持久化并投影状态；浏览器只通过一个 `/json/stats.json` 文档呈现 Home、Hardware、Docker、Lucky、EasyTier 与 UniFi。

## 功能范围

- **多设备**：Device v2 以显式 Registry、独立 token digest 与 HTTPS 上报维护设备身份。Registry 的 `display_name` 是浏览器展示名称的权威来源；Client hostname 不能覆盖它。
- **主机与硬件**：CPU、内存、系统运行时间、操作系统、磁盘、SMART、温度、通电时间、文件系统和存储卷。磁盘、设备和文件系统都必须显式授权；不会扫描完整宿主机根目录或完整 `/dev`。
- **Docker**：只读 Docker socket 采集容器状态与安全的摘要字段。
- **Hermes**：已安装时显示 Profile 摘要；未安装是可用的可选状态，不会让设备离线或全局降级。
- **Lucky**：严格回环的只读 HTTP(S) API 采集版本、DDNS、Web 服务、端口转发和证书摘要。token 只能从受保护文件读取。
- **EasyTier**：只读 CLI 与回环 RPC 采集节点、Peer、Route、Connector、流量与 Configured-vs-Observed。无远端节点、未观察到直连/中继或可选功能未配置都不是故障。
- **UniFi（2.5）**：显式 profile 驱动的只读 SSH 遥测，V1 支持 UDW 与 UCG Max 的 CPU、内存、温度、运行时间、负载及已证实的风扇/电源/存储能力语义；可选的本地 UniFi API 使用文件化 `X-API-Key` 与证书指纹校验。

网络吞吐、三网/运营商延迟探测、EasyTier 管理、远程命令执行、自动注册、历史数据库和告警不属于产品范围。

## UniFi 2.5 边界

UniFi 目标必须由管理员在 Device v2 配置中显式选择 profile（当前为
`udw`、`ucg-max`）。SSH 使用固定的只读命令序列、严格
`known_hosts` 校验和文件凭据；API 使用本地控制器的 `X-API-Key`，不会
把密码、API key 或 host key 写入环境变量、命令行、日志、遥测或页面。
采集器主机的在线状态与远端 UniFi 目标状态相互独立。

2.5 已实现的 UniFi 观测包括 CPU/内存/负载/温度、运行时间、端口状态、
PoE、错误/丢弃，以及在目标 API 提供时仅针对网关 WAN1/WAN2 等 WAN 接口的基本状态；设备上行口不会混入 WAN 表。更丰富的 ISP/ASN、
最新测速和 SLA/丢包语义的数据源已经确认，但完整投影延后到 2.6；这是
HermesStatus 集成的后续增强，不代表 UniFi 不提供这些 API。

## 架构

```text
authorized host inputs / Docker / Hermes / Lucky / EasyTier / UniFi
                         ↓
                  Python Client
                         ↓
      Device v2 HTTPS or compatible Legacy TCP transport
                         ↓
                     Go Server
                         ↓
        /json/stats.json · /api/health · Web UI
```

Server 不读取 Docker socket、Lucky credential、EasyTier 配置或原始 CLI 输出。所有输入都在 Client 边界做 allowlist、长度、类型与秘密过滤；Server 只接受严格验证后的投影。

## 快速开始

服务端与 Client 使用 Compose 配置。生产配置、token、密码、私有 CA 和私网地址均不得提交到仓库；发布部署必须使用同一 full
revision 对应的不可变 `2.5-<sha12>` 镜像标签，不使用 `2.5` 或 `latest`。

```bash
docker compose --env-file /secure/path/server.env \
  -f docker-compose-server.yml up -d --build

docker compose --env-file /secure/path/client.env \
  -f docker-compose-client.yml up -d --build
```

默认 Web 地址是 `http://127.0.0.1:8080/`；状态文档为 `/json/stats.json`，健康端点为 `/api/health`。生产 Device v2 应仅暴露在固定 HTTPS 反向代理路径后，启动前执行：

```bash
serverstatus --validate-device-config \
  --device-registry /absolute/path/devices.json \
  --device-credentials /absolute/path/credentials.d \
  --legacy-device-mapping /absolute/path/legacy-device-mapping.json
```

## 最小权限硬件采集

不要为了 SMART 或文件系统观测使用 `privileged`、`SYS_ADMIN`、完整 `/dev` 或整个宿主机根目录。仅为已确认设备提供只读映射，例如：

```yaml
cap_add:
  - SYS_RAWIO
devices:
  - /dev/sda:/dev/sda:r
environment:
  SMART_DEVICE: /dev/sda
```

多盘使用 `hardware.smart_devices` 逐项 allowlist；文件系统仅通过 `hardware.filesystem_probes` 的固定挂载点和只读 probe path 采集。详情见[设备配置指南](docs/zh-CN/DEVICE_CONFIGURATION.md)和[硬件设计](docs/design/HARDWARE_MONITORING.md)。

## 当前已知限制

- EasyTier 2.6.4 的某些 CLI 输出会把本地节点列入 peer 列表；远端 peer 摘要会按 own peer ID 严格排除该行。原始连接信息仍可能存在版本差异，不能据此过度推断拓扑。
- 未映射或物理存在未知的风扇、PSU、NVMe 与传感器保持 `unknown` / diagnostics，不能仅由 `0 RPM`、异常低温或未出现块设备推断为故障或不存在。

## 文档与验证

- [架构](docs/zh-CN/ARCHITECTURE.md) · [配置](docs/zh-CN/CONFIGURATION.md) · [部署](docs/zh-CN/DEPLOYMENT.md)
- [安全](docs/zh-CN/SECURITY.md) · [运维](docs/zh-CN/OPERATIONS.md) · [开发](docs/zh-CN/DEVELOPMENT.md)
- [Device v2 配置指南](docs/zh-CN/DEVICE_CONFIGURATION.md)
- [Unified Client configuration](docs/UNIFIED_CLIENT_CONFIG.md)
- [EasyTier 监控设计](docs/zh-CN/EASYTIER_MONITORING.md) · [硬件监控设计](docs/zh-CN/HARDWARE_MONITORING.md) · [UniFi 监控设计](docs/zh-CN/UNIFI_MONITORING.md)

```bash
(cd server && go test ./...)
(cd clients && python3 -m unittest discover)
(cd scripts/tests && python3 -m unittest discover)
node --test web/js/app.test.js
docker compose -f docker-compose-client.yml config --quiet
```

GK50/Linux 的统一配置路径是
`/home/hermes/status/config/client-config.json`，Synology DSM 是
`/volume1/docker/status/config/client-config.json`；两者均只读映射到
`/run/secrets/hermesstatus/client-config.json`。Device v2 token 保持独立只读
挂载到 `/run/secrets/hermesstatus-device-token`。Synology 的候选 Compose、
权限和停止旧 Client 再启动新 Client 的回滚流程见
[`deploy/compose/README.md`](deploy/compose/README.md) 与
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)。

## 许可

[MIT License](LICENSE)
