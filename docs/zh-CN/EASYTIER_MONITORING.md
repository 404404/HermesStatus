# EasyTier 监控设计（2.3 Preview）

[English](../design/EASYTIER_MONITORING.md) · [文档目录](README.md)

## 范围与安全边界

EasyTier 仅提供只读监控，不提供管理能力。Client 只允许通过 loopback RPC
调用五个 CLI 检查命令：`node info`、`peer list`、`route list`、`connector list`
和 `stats show`。RPC portal 只接受 `127.0.0.0/8` 或 `::1`；子进程使用 argv
数组且 `shell=False`。不允许连接器、路由、白名单、端口转发、凭据、日志或
服务重启命令。

数据投影只保留有界的 Node、Peer、Route、Connector 和 EasyTier 自身流量
计数。仅允许内部 Overlay IPv4 与 RFC1918/RFC4193 proxy CIDR。公网端点、DDNS
主机名、URL query、STUN、凭据、原始配置、原始命令输出和 stderr 都不会进入
Server、持久化或浏览器。

## 语义

`direct` 需要目标 peer ID 与 next-hop peer ID 相同并且存在直接连接证据；
next hop 不同才是 `relayed`，证据不足为 `unknown`。远端 Peer 为 0 时，Direct、
Relay 以及 IPv6 UDP Direct 都为 `not_observable`，不是 0 或 false。

TCP Listener Available、TCP Connector Configured 与 TCP Active 是三个独立
字段。当前支持基线为 `2.6.4-8428a89d`；兼容性按字段、类型、枚举和边界的
schema family 判断，可兼容 2.6.x。未知或不兼容结构显示
`unsupported_version`，不会崩溃、透传原始 JSON 或静默损坏。

Registry 可选的 `easytier_expectation` 比较管理角色、网络名、Overlay IPv4
和内部 Proxy CIDR。它只用于运维诊断，绝不用于设备身份、认证、注册或凭据
选择。未观察到的数据为 `not_observable`；某条命令失败不会伪造空数组，而会
明确显示该视图不可用。

## 资格验证

当前仅完成 GK50 的真实 zero-peer 采集资格验证。Direct IPv6 UDP、Relay、
TCP active、未来远端私网 CIDR、Expectation mismatch 与部分失败均由明确
标记为 synthetic 的 Fixture 验证，不能描述为真实网络已验证。Synology 加入后
仍需完成真实双站点验证。2.3 staging 独立使用 21443，不修改 2.2 容器、镜像、
配置、状态或网络。
