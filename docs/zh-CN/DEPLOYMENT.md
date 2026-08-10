# 部署

[English](../DEPLOYMENT.md) · [文档目录](README.md)

## 本地 Compose

仓库提供 `docker-compose-server.yml` 与 `docker-compose-client.yml`。在检查环境变量和挂载后，可用于本地验证：

```bash
docker compose --env-file /secure/path/server.env \
  -f docker-compose-server.yml up -d --build

docker compose --env-file /secure/path/client.env \
  -f docker-compose-client.yml up -d --build
```

生产环境使用受保护的环境文件。不得把生产 token、密码、设备 credential 或私有地址写入仓库。

## 生产边界

候选版本使用独立 Compose 项目、数据目录、Client 状态目录和主机端口。验证完成后才替换原部署。为 Server 与 Client 记录完整源代码 revision 以及不可变镜像 ID/digest，不能只依赖 tag。

服务端提供 WebUI/API，按需提供 Legacy TCP 监听。启用 Device v2 时，只将 v2 POST 路径放在 HTTPS 反向代理后；不得把设备更新后端直接暴露到互联网。

## EasyTier Preview 与发布

启用 EasyTier 的候选版本必须使用独立 Compose 项目、Registry、credential 目录、状态目录、Client 状态目录以及 HTTPS 主机端口。该端口必须显式绑定到 overlay 或局域网所用的私有网卡（例如 EasyTier 网卡），不得绑定到 `0.0.0.0` 或公网地址。只读挂载 EasyTier CLI 二进制到 Client；不要挂载其配置或秘密。若 Device v2 使用 TLS 代理，Server 的受信代理 CIDR 只能包含该代理，后端 HTTP 必须保持在 Compose 网络内。提升前，在 `/json/stats.json` 中确认选定设备、`easytier.status` 与五个命令状态；单节点 overlay 的远端节点数为零是有效状态。

## SMART 设备访问

SMART 采集需要访问真实块设备的 ioctl。单盘监控时，不要把 Client 改为 privileged，也不要挂载完整 `/dev`。对于 `/dev/sda`，最小 Compose 配置为：

```yaml
cap_add:
  - SYS_RAWIO
devices:
  - /dev/sda:/dev/sda:r
environment:
  SMART_DEVICE: /dev/sda
```

这段配置应替换而非叠加在 `docker-compose-client.yml` 中遗留的宽泛设置上：添加 capability 和单设备映射前，设置 `CLIENT_PRIVILEGED=false`，并删除 `/dev:/dev:ro` 卷挂载。仓库 Compose 文件为兼容性保留这些旧默认值；若仍保留它们，就不是最小权限部署。

保留只读根文件系统和 `no-new-privileges`。如果主机使用其他磁盘路径、RAID 或 NVMe 控制器，先确认并验证该具体设备，不能仅为自动发现而扩大设备权限。

## 健康检查

```bash
curl -fsS http://127.0.0.1:<web-port>/api/health
curl -fsS http://127.0.0.1:<web-port>/json/stats.json
docker compose -p <project> ps
```

检查 Client 健康状态和重启次数，再确认 `stats.json` 中目标设备 SMART 状态不为 `unknown`。

## 2.3 Preview staging

`2.3-preview` 必须使用独立的 Compose 项目、状态目录、Registry、凭据、网络
和候选镜像。当前 Preview 主机端口为 21443，升级时沿用既有 staging 绑定策略，
不得擅自放宽。变更前记录 2.2 的容器 ID、镜像、OCI label、端口、挂载、网络和
重启次数；2.3 Preview 不得停止、重建或修改 2.2。

只从干净的候选 commit 构建，并使 Server 和 Client 的 OCI revision 精确等于
该 commit。备份 Preview 配置和状态，安全升级现有 Preview 项目，再验证 health、
stats、Device v2 上报、服务端重启及 down/up 后的持久化，以及重启次数为零的
观察窗口。
