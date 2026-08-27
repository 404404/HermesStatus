# 架构

HermesStatus 是一个小型、只读的监控系统。Client 采集受限的主机观测并发送给 Server；Server 校验、持久化已接受状态；Web UI 只读取 Server 的统一统计投影。

```text
主机观测 -> Client -> Device v2 HTTPS -> Server -> /json/stats.json -> Web UI
```

## 设备身份与数据流

Device Registry 是 `device_id`、`display_name`、启用状态与协议的权威来源。Client 上报的 hostname 只是观测数据，不能重命名 Registry 设备。Device v2 使用每设备凭据摘要、TLS、重放/冲突检查及 Server 权威生命周期状态。已显式配置的 Legacy 上报仍兼容。

已接受更新以原子方式写入；过期、冲突或无效上报不会覆盖最后一次已接受状态。Server 重启后恢复的数据在收到新的已接受上报前始终为 stale。

## 监控域

当前投影包含相互独立的只读域：

- 硬件与操作系统；
- Docker；
- 已安装时的 Hermes Agent Profiles；
- Lucky；
- EasyTier；
- 显式配置 Client-side profile 时的 UniFi target。

域可独立处于 fresh、partial、degraded、unavailable 或 not_configured，不会让无关域变为失败。可选 Hermes Agent 的 `not_installed`，或可用的 SMART 属性回退，均不会单独使设备离线或不健康。

硬件将物理磁盘与卷/文件系统分开，RAID、device-mapper 与 DSM 卷无需伪造为某一块物理盘的附属物。

## 信任边界

Collector 使用固定 allowlist 与解析器，不提供远程 shell、任意命令执行、配置编辑或控制平面。敏感原始对象、凭据、私有端点和 EasyTier 配置不会持久化或展示。Web UI 安全渲染非信任字符串，并在所有页面共享一个 stats 文档/fetch 路径。

## EasyTier 模型

EasyTier 仅用于监控。Client 使用配置好的 loopback RPC 与固定只读 CLI，绝不管理 connector、route、credential、端口转发、日志或服务重启。`supported`、`present` 与 `observed` 是不同概念，不能由 0 RPM、缺失设备或缺失 peer 推断。

无远端 peer 时，Direct、Relay 与 IPv6-UDP-Direct 为 `not_observable`，而不是 false 或 0。当前版本已知局限：部分 EasyTier 2.6.4 输出会在 peer 列表中包含本机节点，因此远端 peer 汇总在修复本机 peer 过滤前可能偏大。

## 明确不在范围内

HermesStatus 不是 EasyTier 管理器、远程执行服务、告警系统、时序数据库、拓扑编辑器，也不是通用网络流量或运营商探测产品。

## UniFi 机型 Profile

UniFi V1 是远端观测域，不是第二套 Client 身份或控制通道。Device v2 Client 每个采集周期只执行一次有界、固定的 OpenSSH session，并且仅规范化 symbolic source：`ubnt-systool cputemp`、聚合 `/proc/stat`、选定的 `/proc/meminfo`、`/proc/uptime` 与 `/proc/loadavg`。Server 只接收有界的遥测投影。

profile 由管理员显式选择并 fail-closed。UDW 与 UCG Max 共用 Generic Collector，风扇、PSU、thermal 和 NVMe 差异只在 profile 数据中表达。`supported`、`present`、`observed` 必须分离：0 RPM、未观察到的块设备或可选诊断源均不能推断物理故障。UniFi 传输失败只会使 UniFi target stale，不能修改 Device v2 身份，也不能使采集主机离线。
