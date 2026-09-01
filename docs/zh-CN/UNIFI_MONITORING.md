# UniFi 监控（V1）

UniFi 监控是 HermesStatus 2.6 开发线中 profile 驱动、只读的远端观测域。它有意只覆盖已完成资格验证的 UDW 与 UCG Max console 机型；不是 UniFi controller 集成、设备发现、资产清单、管理 API、远程 shell 或配置通道。

## 数据模型

```text
固定 symbolic source registry
        ↓
固定单 session OpenSSH 采集
        ↓
有界 raw observation
        ↓
runtime UniFi identity + 冻结 Catalog bundle
        ↓
静态能力投影 + runtime observation
        ↓
normalized UniFi telemetry
        ↓
Device v2 → Server → /json/stats.json → UniFi 标签页
```

两个 profile 共用 Generic Collector V1：`ubnt-systool cputemp`、聚合 `/proc/stat`、选定 `/proc/meminfo`、`/proc/uptime` 和 `/proc/loadavg`。CPU 百分比取两个成功的 aggregate sample，并排除 idle 与 iowait。因此第一个成功样本为 `cpu_usage_pct=null` 与 `insufficient_delta`，绝不伪造为零。内存已用为 `MemTotal - MemAvailable`；仅当 `MemAvailable` 缺失时，才使用已记录的 `MemFree + Buffers + Cached` 回退。

## Catalog consumer 边界

静态硬件能力从 `clients/unifi_catalog/` 中随版本固定的 deterministic bundle 读取；该 bundle 来自 `404404/UniFi_Catalog` revision `714a3c8ce1a7d6d5165aad66912ea2db5ed55563`，bundle SHA-256 为 `a92a44e5ef2f4afa20620782f4ecfb539bd72a18f86d5480d4110846f9f4d13b`，并由 SHA-256 manifest 校验。物理端口、存储、电源、PoE 和已确认处理器事实均以 bundle 为权威来源，HermesStatus 不维护平行机型表。

采集 profile 由管理员显式选择，但它不是硬件 identity，也不能解锁静态能力。controller 的 `api_model`、`sysid` 和 SSH model string 都是 runtime identifier；只有 Catalog 中标为 `verified` 的 alias 才能解析 canonical SKU。candidate alias 和未知字符串仍保留为 runtime observation，但不能解锁静态能力。只有 verified runtime resolution 成功后，才能单独投影静态能力；API 观测保留在 `api` 下。

物理端口使用稳定的 `(device_id, port_idx)` 连接。静态端口名称和能力只附加到相同设备身份及物理索引；缺少 runtime 行时可以产生 static-only 行，未知机型则只保留 runtime 行，不伪造静态字段。电源输出区分机型级 `absolute_max_poe_budget_w` 与具体 `power_profiles[].poe_budget_w`；null 始终表示未知。

## Profile 与能力语义

profile 仅能显式选择（`udw` 或 `ucg-max`），未知 profile 会被拒绝。采集 profile 表达 telemetry 与 diagnostic source，而 normalized payload 另行保留 `supported`、`present`、`observed`；三者不能互换。

- 风扇能力绝不从采集 profile 读取。当前冻结 Catalog 将 UDW 与 UCG Max 的 fan capability 保持为 `unknown`；有界的 `fanN` 转速观测会以 `supported=unknown`、`present=unknown` 保留，直到 Catalog 有权威的物理分类。RPM 为零仍是 `observed_zero_rpm`，绝不是故障。
- UCG Max 有五个 thermal zone；已确认 `lm63` 的 `fan1_input` 是 hwmon RPM 观测。冻结 Catalog 是其存储、电源、PoE、端口和处理器能力的权威来源；Catalog fan classification 未知时，不能把该 runtime sensor 变成物理风扇结论。UDW/UCG 的静态能力同样不能由 profile 名称推断。

raw thermal zone、hwmon detail、cpuload diagnostics、PWM、未映射 PSU sensor 和不确定 NVMe diagnostics 不进入 V1 UI，也不自动影响健康。静态存储和电源能力从已验证 runtime model 对应的冻结 Catalog 投影读取；采集 profile 只负责 source 和 formula。未知 runtime model 保留有界 runtime observation，但不投影静态能力，也不会让整个 UniFi domain 失败。UDW 的 `/ssd1` 文件系统使用固定只读 `unifi.udw.ssd_filesystem` source；`capacity_bytes` 始终是物理容量，`filesystem_total_bytes` 是挂载文件系统总量，缺少挂载是可选观测。

## 失败与新鲜度

SSH host-key、认证、超时、传输和解析失败会保留已有有效 UniFi snapshot（若有），标记 UniFi `stale=true` 并暴露结构化安全错误；无历史结果时，遥测值必须为 null 而不是零。下一次有效结果会清除 stale/error。Server 将其视为远端 target 状态：绝不改变 Device v2 采集主机的身份、在线状态、硬件状态或无关域健康。

## 安全边界

profile 文件不能定义 command。代码侧 source registry 没有任意远端 path 或 shell 扩展点。transport 使用固定打包 script、argv 执行、有界 output/timeout、严格 known-host 校验和受保护文件的 keyboard-interactive 认证。不会持久化或展示凭据、raw output、私有 endpoint、controller 配置或远端命令结果。

## 初始 UI

UniFi 标签页只呈现 profile、传输/新鲜度、CPU 使用率、CPU 温度、内存、uptime、load 与有界的 fan/PSU/storage capability 状态。端口标签按权威设备 identity 分组、按管理 IP 数值排序；标签文字保持一行，设备多时标签行自动换行；明确离线的设备名称追加 `（离线）`。它复用浏览器现有的单一 stats 文档和刷新 timer，不会建立独立 polling endpoint。
