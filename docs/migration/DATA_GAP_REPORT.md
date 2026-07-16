# HermesStatus 数据缺口报告

## 目录

- [结论](#结论)
- [评估标签](#评估标签)
- [P0 覆盖矩阵](#p0-覆盖矩阵)
- [关键缺口](#关键缺口)
- [安全缺口](#安全缺口)
- [刷新与错误缺口](#刷新与错误缺口)
- [B1 B2 B3 阻断项](#b1-b2-b3-阻断项)
- [未验证项](#未验证项)
- [非缺口项](#非缺口项)
- [退出标准](#退出标准)
- [关联文档](#关联文档)

## 结论

HermesStatus 2.0 的原生 Go 链路已经能传输 CPU、内存、硬盘、uptime、OS 和 CPU model，但 OS 与默认 psutil CPU model 的来源不满足物理机语义。Hardware、Docker、Hermes 三个扩展域在 2.0 当前业务代码中均未实现；即使直接运行 1.0 client，legacy `*_json` 字段也会在 Go `json.Unmarshal` 时被静默忽略。

当前已确认 Dashboard 是可用的界面壳和 fixture 消费者，不是实数管线完成证据。开始任何业务迁移前，必须先解决数据所有权、来源准确性、secret/error 脱敏和领域 freshness。

## 评估标签

| 标签 | 定义 |
| --- | --- |
| `PRESENT_OK` | 采集、传输、快照与消费均存在，来源符合目标 |
| `PRESENT_WRONG_SOURCE` | 字段存在，但读取了容器或不稳定来源 |
| `COLLECTOR_MISSING` | 2.0 client/exporter 没有采集能力 |
| `WIRE_DROPPED` | 数据到达 TCP body，但反序列化忽略 |
| `SNAPSHOT_MISSING` | Go state/HTTP 未映射 |
| `CONTRACT_ONLY` | Schema/fixture 有定义，业务代码没有 |
| `UI_ONLY` | 前端已消费字段，真实后端没有 |
| `UNVERIFIED_HOST` | 代码明确但尚无目标主机证据 |

## P0 覆盖矩阵

| HS | 功能 | Source | Collector | Wire/Go model | Snapshot/API | 当前 Dashboard | 总体状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HS-004 | 宿主机身份 | 1.0 正确；2.0 OS/psutil CPU model 不正确或不稳 | 2.0 原生存在 | 原生字段贯通 | 原生输出 | 已消费 | `PRESENT_WRONG_SOURCE` |
| HS-005 | CPU 温度 | hwmon 明确 | 2.0 缺失 | 缺失 | 缺失 | 已消费 | `COLLECTOR_MISSING` + `UI_ONLY` |
| HS-006 | SMART 健康 | smartctl 文本优先路径明确 | 2.0 缺失 | 缺失 | 缺失 | 已消费 | `COLLECTOR_MISSING` + `UNVERIFIED_HOST` |
| HS-007 | SMART 温度三值 | Device Statistics 偏移明确 | 2.0 缺失 | 缺失 | 缺失 | 已消费 | `COLLECTOR_MISSING` + `UNVERIFIED_HOST` |
| HS-008 | 通电小时/累计 I/O | Device Statistics 明确；扇区换算需修订 | 2.0 缺失 | 缺失 | 缺失 | 已消费 | `COLLECTOR_MISSING` + `UNVERIFIED_HOST` |
| HS-009 | Docker 清单 | Engine list API 明确 | 2.0 缺失 | 缺失 | 缺失 | 已消费 | `COLLECTOR_MISSING` + `UI_ONLY` |
| HS-010 | Profile 注册 | 1.0 注册表明确 | 2.0 exporter 缺失 | 缺失 | 缺失 | 已消费 | `COLLECTOR_MISSING` + `UI_ONLY` |
| HS-011 | 周期快照/freshness | 1.0 有文件快照，无完整领域时间 | 2.0 缺失 | 合同已有草案 | 缺失 | 顶栏时间语义不正确 | `CONTRACT_ONLY` |
| HS-021 | 凭证安全 | 1.0 API key 边界基本正确 | 部分字段仍可能泄露路径/error | Go allowlist 已实现 | 结构化安全错误 | Docker command 已删除 | Release C 收敛完成 |
| HS-022 | 扩展协议 | 1.0 JSON-in-string | 1.0 有；2.0 无 | Go 静默丢弃 | 缺失 | 期望对象 | `WIRE_DROPPED` + `SNAPSHOT_MISSING` |
| HS-023 | 容器化宿主机访问 | 1.0 Compose 有挂载/权限 | 2.0 Compose 未移植 | 不适用 | 不适用 | 间接依赖 | `COLLECTOR_MISSING` + `UNVERIFIED_HOST` |

## 关键缺口

### G-01 扩展在 Go 入口静默丢失

- 严重度：P0 blocker。
- 证据：`server/tcp_server.go` 将 update 直接反序列化到 `AgentStats`；`server/model.go` 没有扩展字段。
- 行为：旧 `hardware_json/docker_json/hermes_json` 与未来同名结构化对象都会作为未知字段被忽略。
- 影响：基础资源正常更新，扩展悄悄消失，最难从表面连接状态发现。
- 后续：B2 必须有 legacy/structured 输入测试，断言 stats 字段不丢失。

### G-02 2.0 没有 P0 扩展 collector

- 严重度：P0 blocker。
- 证据：2.0 没有 exporter、config summary、注册表；client 没有 hwmon/SMART/Docker/Profile 快照代码。
- 影响：即使 Go 类型完成，也没有真实数据输入。
- 后续：按 [DATA_SOURCE_DECISIONS.md](DATA_SOURCE_DECISIONS.md) 复用并收敛 1.0 Python 采集器，不在同一 PR Go 化。

### G-03 OS 字段读取容器系统

- 严重度：P0 correctness。
- 证据：2.0 两个 client 读取 `/etc/os-release` 的 `ID`；Compose 没有宿主机 `os-release` 挂载。
- 影响：Dashboard 可能显示 client 镜像发行版而非物理机完整版本。
- 后续：使用只读宿主机文件并取 `PRETTY_NAME`，保留安全 fallback。

### G-04 默认 psutil CPU model 可能退化

- 严重度：P0 correctness。
- 证据：默认 `CLIENT=psutil`，`get_cpu_model()` 只检查 `platform.processor/uname`，随后返回 vendor/arch；没有读取 `lscpu` 或 `/proc/cpuinfo` 的 model name。
- 影响：可能显示 `Intel`、`x86_64` 等泛化值。
- 后续：采用与 1.0 一致的宿主机 model name 来源；UI 单行自适应已经完成。

### G-05 SMART 双重所有权与高频执行

- 严重度：P0 reliability/performance。
- 证据：exporter 每 600 秒执行 SMART；psutil client 的每秒 update 又调用 `get_hardware_health()` 并执行 SMART。
- 影响：重复命令、来源竞争、时间戳与值不是同一次采集，潜在磁盘/CPU 开销。
- 后续：只保留一个 SMART 所有者，统一 600 秒 hardware 快照。

### G-06 累计 I/O 固定乘 512

- 严重度：P0 correctness。
- 证据：ATA Logical Sectors Written/Read 均直接乘 512。
- 影响：对非 512 逻辑扇区设备可能错误。
- 后续：从 smartctl information/JSON 获取 logical sector size；无法确认时输出 null + error，不猜测。

### G-07 freshness 与 UI 刷新时间不一致

- 严重度：P0 observability。
- 证据：1.0 只有 exporter hardware 有 `updated_at`；Docker/Hermes/Profile 没有。当前 Dashboard 顶栏记录浏览器 fetch 成功时间。
- 影响：10 分钟甚至更旧的 Hermes 快照可显示为“刚刷新”。
- 后续：每域/Profile 输出采集时间；浏览器 fetch 时间不得替代数据时间。

### G-08 Fixture 适配器不等于真实 stats 管线

- 严重度：B3 integration blocker。
- 证据：Dashboard 本地 fixture 是 extension root，JavaScript 在 fixture mode 下人工包装成一个 host。
- 影响：前端测试可通过，而 Go TCP -> NodeState -> stats 仍完全缺失。
- 后续：增加真实 `servers[].hardware/docker/hermes` stats fixture 和 Go HTTP 集成测试。

## 安全缺口

| 编号 | 1.0 行为 | 风险 | Release A 要求 |
| --- | --- | --- | --- |
| S-01 | Docker `command` 仅截断 | 命令参数可能带密钥或凭证 | Release C 已从采集、合同、stats 和 UI 完全删除 |
| S-02 | Docker error 使用 `str(e)` | Socket 路径、系统错误细节进入 stats/browser | 固定 code/source/retryable，message 限长脱敏 |
| S-03 | Hermes `note` 混合 API 错误和 Profile 目录 | 真实路径或连接细节进入浏览器 | 删除 note 作为业务字段，改结构化 error |
| S-04 | config summary 输出 `config_path/checked_paths/docker_volumes` | 暴露宿主机目录结构 | Release A 不输出；Release B 单独定义路径显示策略 |
| S-05 | `disk_smart_source` 保存完整命令 | 暴露设备和执行方式 | 固定枚举，如 `smartctl_text` |
| S-06 | C++ 原样嵌入 legacy JSON | server 无白名单，collector 误发即透传 | Go 解析、验证、丢弃 raw string |
| S-07 | Docker Socket bind 标记 `ro` | API 权限仍接近 root | 只读 allowlist 是代码约束，不是 mount 保证；部署风险需注明 |

1.0 的 Hermes API key 正常路径没有进入 wire 或 stats，现有安全测试通过；迁移时必须保留这一边界。

## 刷新与错误缺口

| 数据域 | 1.0 error | 1.0 时间 | 合同目标 | 缺口 |
| --- | --- | --- | --- | --- |
| Native | 异常通常中断 update/re连 | server root `updated` | 沿用原生连接状态 | 无领域诊断 |
| Hardware | 多数失败变 null/unknown，无 error | 仅 exporter snapshot | `updated_at/stale/error` | direct fallback 与 snapshot 混合 |
| Docker | 自由文本 error | 无 | 结构化 error + 120 秒 stale | 全部缺失 |
| Hermes root | client 扫描异常自由文本 | 无 | root partial error + 900 秒 stale | 全部缺失 |
| Profile | `note` 拼接错误 | 无 | Profile 独立 error/time | 全部缺失 |
| Token | 无值时 0 + estimated | 无 window | nullable/diagnostic | 1.0 容易被误解为真实 0 |

## B1 B2 B3 阻断项

这里的 B1/B2/B3 表示后续实施门，而不是本次文档 PR。

### B1 数据源与 collector 门

- [ ] 实机确认 OS、CPU model、内存、根盘、uptime 的 host/container 一致性。
- [ ] 固定 hwmon CPU 温度选择规则和目标 smart device。
- [ ] 确认 smartctl 文本/JSON输出、logical sector size、Device Statistics 支持。
- [ ] 指定 SMART 单一所有者，取消每秒重复执行。
- [ ] 指定 Docker 采集周期、命令隐藏/脱敏策略和 error 映射。
- [ ] 固定 Profile 注册表、状态目录、刷新时间和失败隔离。
- [ ] 所有 collector 输出通过 Schema 且无 secret/path/raw error。

### B2 Go 模型与管线门

- [ ] `AgentStats` 扩展类型、枚举、字符串/数组/字节上限已实现。
- [ ] 结构化对象和 legacy `*_json` 均有明确解析优先级。
- [ ] 扩展域失败不阻断基础 update。
- [ ] `NodeState`、`SnapshotStats`、stats 持久化和 restart 语义有测试。
- [ ] 服务端重算 stale，root stats 时间不覆盖领域时间。
- [ ] OpenAPI 只描述脱敏白名单字段。
- [ ] 旧客户端无扩展仍保持兼容。

### B3 Dashboard 与部署门

- [ ] Dashboard 使用真实 `servers[]` stats fixture，而不是只用 extension-root adapter。
- [ ] normal/empty/degraded/long-values 在真实 Go HTTP 输出上通过。
- [ ] host OS、CPU model、SMART、Docker 数量与主机命令一致。
- [ ] 两容器 Compose 的挂载、权限、健康检查、自启动和回滚验证完成。
- [ ] 浏览器网络响应、DOM、日志和截图均无 secret/真实敏感路径。
- [ ] 上次刷新与 stale 文案使用领域时间，不伪装新鲜。

## 未验证项

| 项目 | 原因 | 验证位置 | 阻断阶段 |
| --- | --- | --- | --- |
| 远端 1.0/2.0 基线 | 已在提交前 fetch；2.0 与工作分支基线均为 `70d996e` | 每个后续实现 PR 再次 fetch/compare | 已确认，不阻断 B0 |
| 当前目标 CPU model/OS | 本阶段未执行远程命令 | 物理机 + client 容器 | B1 |
| hwmon label 与温度 | 设备相关 | 物理机 + client 容器 | B1 |
| SMART 设备、健康、三温、小时、I/O | 设备/权限相关 | 物理机 + client 容器 | B1 |
| 逻辑扇区大小 | 设备相关 | smartctl information/JSON | B1 |
| Docker API 实机字段/上限 | Engine 与容器集合相关 | host CLI + Socket | B1/B3 |
| Hermes API JSON 形状 | 当前实例/版本相关 | client 容器内脱敏审计 | Release B |
| Go 自动测试 | 本机无系统 Go toolchain | CI 或 Go 开发容器 | B2 |

## 非缺口项

- Go TCP scanner 的 1 MiB 总上限大于 1.0 的 64 KiB wire 上限；问题是类型和验证，不是总 buffer 太小。
- 2.0 原生管理 API、OpenAPI、SSL 状态检查和配置能力保留；Release C 删除告警引擎与通知回调。
- Runs、聊天、停止、审批不是 1.0 已交付能力，不属于迁移缺口。
- `/api/hermes/config-summary` 不在 Release A，缺少该路由不是 P0 缺口。
- 当前 Dashboard 的布局、CPU 单行适配和硬盘通电时间天数样式已经由用户确认；本报告不要求重做样式。

## 退出标准

本数据审计可进入实现阶段的最低条件：

1. [DATA_SOURCE_MAP.md](DATA_SOURCE_MAP.md) 所有 P0 “待实机”项有脱敏证据或明确接受的 unavailable 行为。
2. [DATA_SOURCE_DECISIONS.md](DATA_SOURCE_DECISIONS.md) 中 Proposed/Blocked 决策完成确认。
3. B1/B2/B3 的 PR 顺序、文件边界和回滚点按 [MILESTONE_B_PR_PLAN.md](MILESTONE_B_PR_PLAN.md) 锁定。
4. [x] GitHub 远端引用已重新同步；本报告基于 `hermesstatus/1.0@36168a6` 与 `hermesstatus/2.0@70d996e`。
5. 不开始 Runs、聊天、完整 Hermes P1/P2 或 collector Go 化。

## 关联文档

- 数据来源：[DATA_SOURCE_MAP.md](DATA_SOURCE_MAP.md)
- 端到端链路：[SOURCE_TRACE.md](SOURCE_TRACE.md)
- 决策：[DATA_SOURCE_DECISIONS.md](DATA_SOURCE_DECISIONS.md)
- PR 计划：[MILESTONE_B_PR_PLAN.md](MILESTONE_B_PR_PLAN.md)
