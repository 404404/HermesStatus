# EasyTier 监控设计

EasyTier 是只读 Client 域。它通过固定本地 CLI 与 loopback RPC 采集受限的节点、peer、route、connector 和流量投影，不会管理 EasyTier。

## 数据模型

Server 只保存经过严格校验的白名单字段。节点、采集状态、peer、route、connector、流量与可选 expectation 独立保存。原始配置、端点地址、凭据、密钥和任意 feature object 均被排除。

仅当有 direct connection evidence 且 target/next-hop ID 一致时 path 才是 `direct`；ID 不同才是 `relayed`；否则为 `unknown`。transport 与 address family 是独立枚举。没有远端 peer 时，Direct、Relay 与 IPv6 UDP Direct 均为 `not_observable`。

expectation 是操作员诊断，不是设备身份。它可比较 network、overlay address、proxy CIDR 与 administrative role，但不能选择凭据、认证设备或自动注册。

## 采集语义

每条固定命令都独立记录状态与时间。部分命令失败时不得伪造空列表：有 last-known data 则保留，否则明确标记该数据 unavailable。只有 Server 时钟下收到已接受上报后域才是 fresh。未知 schema/version 应报告 unsupported，不能透传 raw 数据。

## 安全边界

运行时 allowlist 只有只读查询，排除 connector、route、credential、whitelist、port-forward、logger 和 service lifecycle 命令。RPC 只允许 loopback。UI 读取既有 stats 文档，不创建 EasyTier 控制接口。

## 当前限制

部分 EasyTier 2.6.4 输出可能在 peer-list 响应中包含本机节点。当前 2.0 可能将该行计入远端 peer 汇总；计划通过严格 own-peer-ID filter 修复。修复前不要把受影响汇总当作拓扑事实。
