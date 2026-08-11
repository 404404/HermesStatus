# 安全

[English](../SECURITY.md) · [文档目录](README.md)

## 信任边界

Server 只负责状态投影：它不挂载 Docker socket，也不读取 Hermes 或 Lucky 的宿主机秘密。Client 是高信任组件：它读取主机文件、可选硬件设备、Docker socket 与指定 Hermes/Lucky 输入，再向 Server 发送脱敏扩展数据。

Client 只能部署在经过审查的主机。Docker socket 即使以只读方式挂载，也不会使 Docker API 成为只读；采集器在代码中限制为容器列表请求，但 socket 访问本身仍然敏感。

## 秘密

`ADMIN_TOKEN`、Agent 密码、Bearer credential、Lucky token、私有地址和生产配置必须留在 Git 之外，使用受保护文件或 secret mount。不得把秘密写入 Compose、日志、截图、Issue、PR 或文档。

Server 保存 v2 设备 credential digest，而非原始 token。credential 文件支持 current/next 两个轮换槽位。Client 仅向受信任 HTTPS 入口发送原始 Bearer token。

## EasyTier 采集边界

EasyTier 监控只允许通过仅回环 RPC 执行 `node info`、`peer list`、`route list`、`connector list` 与 `stats show`。采集器使用绝对可执行路径和 argv 子进程调用，不使用 shell。投影不包含配置、密钥、credential、RPC 地址、STUN 数据、公网或监听端点、原始 JSON 和 stderr。服务端会在持久化和 UI 投影前拒绝未知字段。

## Device v2 入口

该端点默认关闭。启用后，代理必须提供 HTTPS，只信任显式配置的代理地址转发头，并替换不可信外部转发头。代理只开放指定 POST 路径。服务端会拒绝非法 content type、超大请求体、重复身份头、无效 credential、禁用设备、非活动协议归属、重放冲突与超限请求。

## 安全观测

使用 `/api/health` 与已脱敏的 `/json/stats.json` 排障。不得暴露原始 SMART 输出、Docker API 响应、Hermes 配置、`.env` 或认证头。宁可显示陈旧或不可用状态，也不能伪造健康值。

## EasyTier 监控

EasyTier 只使用 loopback RPC 的只读监控。运行时命令白名单仅包含 `node info`、
`peer list`、`route list`、`connector list` 和 `stats show`；没有 connector/route/
credential/whitelist/port-forward/logger 或 restart 操作。原始配置、端点、凭据、
network secret、Noise key、STUN 地址与命令 stderr 都不会被持久化或渲染。

所有详细字段都由 Server 验证并作为转义文本显示；公网 IP/CIDR 会被拒绝。格式错误、
部分失败或不支持的响应显示为 unavailable/degraded/unsupported，不能伪造成空数据
或健康状态。
