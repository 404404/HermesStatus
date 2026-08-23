# 配置

配置必须显式给出。不要从 hostname、源地址、端口号或 EasyTier overlay 地址推导身份、环境或权限。

## Server 与 Device Registry

Server 配置定义 Device Registry 与 Device v2 凭据。每台设备设置稳定 ID、操作员维护的展示名称、协议模式与启用状态。Device v2 凭据单独 provision：Server 只保存 digest，Client 通过 root-owned secret 文件获得自己的 token。

禁止自动注册设备，也不要将 hostname、peer ID、overlay IP 或源 IP 映射为身份。重启前使用 Server 的设备配置校验命令检查 Registry、凭据与 Legacy 映射。

## Client

每个 Client 使用独立的 root-owned JSON 配置。其 Device v2 区段包含 Registry ID、HTTPS Server URL、CA 文件与 token 文件路径。将 token 与 CA 以只读 secret 挂载；不要放入镜像层、环境变量值、命令行、fixture 或文档。

可选域配置也必须显式：

- `hardware.smart_devices` 是固定磁盘 allowlist；
- `hardware.filesystem_probes` 是固定的窄范围只读探针挂载；
- Lucky 仅允许 loopback URL，TLS 策略与 token 文件均显式配置；
- EasyTier 使用固定本地 CLI、loopback RPC 与可选 administrative role。省略或空的可选 role 都不是非法 role。

完整设备文件、Compose 映射和参数说明见[设备配置](DEVICE_CONFIGURATION.md)。

## 硬件权限

只授予所需设备和路径。SMART 通常只需列出的设备与 `SYS_RAWIO`；不需要 privileged、`SYS_ADMIN`、整个 `/dev` 或无限制的主机文件系统。DSM 身份与数据卷探针必须由部署显式提供窄范围只读挂载，不能使用宽泛默认挂载。

## Lucky 本地 TLS

Lucky 监控只接受 loopback URL。HTTPS/HTTP 与证书验证必须明确配置，不存在“先验证失败后自动关闭验证”的回退。若本地自签名证书必须关闭验证，该例外必须限制在 loopback-only Lucky 边界内，并在部署配置中记录。
