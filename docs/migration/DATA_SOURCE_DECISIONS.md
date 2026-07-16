# HermesStatus 数据源决策

## 目录

- [目的](#目的)
- [状态](#状态)
- [决策总表](#决策总表)
- [DSD-001 采集边界](#dsd-001-采集边界)
- [DSD-002 宿主机身份](#dsd-002-宿主机身份)
- [DSD-003 原生资源口径](#dsd-003-原生资源口径)
- [DSD-004 Hardware 所有权](#dsd-004-hardware-所有权)
- [DSD-005 SMART 解析](#dsd-005-smart-解析)
- [DSD-006 Docker 来源与暴露](#dsd-006-docker-来源与暴露)
- [DSD-007 Profile 注册](#dsd-007-profile-注册)
- [DSD-008 Hermes 字段优先级](#dsd-008-hermes-字段优先级)
- [DSD-009 Token 语义](#dsd-009-token-语义)
- [DSD-010 Freshness 与错误](#dsd-010-freshness-与错误)
- [DSD-011 Wire 与兼容](#dsd-011-wire-与兼容)
- [DSD-012 Secret 边界](#dsd-012-secret-边界)
- [DSD-013 Browser 边界](#dsd-013-browser-边界)
- [待确认决策](#待确认决策)
- [关联文档](#关联文档)

## 目的

本文把 B0 审计后的来源选择固化为实施前置约束。它只做设计决策，不修改 collector、Go server、WebUI、Compose 或配置。

## 状态

| 状态 | 含义 |
| --- | --- |
| Accepted | 已由既有范围合同或 1.0 稳定行为确定，可作为后续 PR 约束 |
| Proposed | 审计建议，需要在对应实现 PR 开始前确认 |
| Blocked | 缺实机或产品证据，不能开始相关实现 |
| Deferred | Release A 不实现，但保留后续来源定义 |

## 决策总表

| 决策 | 主题 | 状态 | 影响里程碑 |
| --- | --- | --- | --- |
| DSD-001 | 第一阶段继续使用 Python 宿主机 collector | Accepted | B1/B2/B3 |
| DSD-002 | OS/CPU model 必须读取物理机来源 | Accepted | B1 |
| DSD-003 | 原生资源字段和单位继续沿用 ServerStatus 协议 | Proposed | B1/B3 |
| DSD-004 | SMART 只有一个采集所有者，Hardware 统一 600 秒快照 | Proposed | B1 |
| DSD-005 | SMART 文本优先且按设备扇区大小换算 | Proposed | B1 |
| DSD-006 | Docker 只调用容器列表 API，容器输出固定四字段 | Accepted | Release C |
| DSD-007 | Profile 名称与路径只由独立注册表驱动 | Accepted | B1 |
| DSD-008 | Hermes 每个字段采用固定 API/CLI/file 优先级 | Deferred | Release B |
| DSD-009 | Token 是 nullable diagnostic，不是账本 | Accepted | Release B |
| DSD-010 | 每域独立时间、stale 和结构化 error | Accepted | B1/B2/B3 |
| DSD-011 | 新结构化 wire，legacy 只作短期输入兼容 | Accepted | B2 |
| DSD-012 | API key 只存在 client；自由文本默认不输出 | Accepted | 全部 |
| DSD-013 | Browser 只读脱敏 stats，不直连宿主机服务 | Accepted | B3 |

## DSD-001 采集边界

**决策：Accepted。** Release A 继续由 Python client/exporter 访问宿主机数据源，Go server 只负责接收、验证、状态、快照和 HTTP 输出。

理由：

- 1.0 的 hwmon、SMART、Docker、Hermes API/CLI/config 行为已有代码和测试。
- 同时 Go 化 collector 与迁移 server 管线会混合来源、协议和部署风险。
- API key、设备和 Docker Socket 留在 client，减少 server/browser 攻击面。

约束：

- 不在 B1/B2/B3 引入 Go SMART、Docker SDK、YAML 或 Hermes client。
- Python 复用不等于逐行复制；必须先消除重复 SMART、原始 error 和 secret 风险。
- collector 输出必须先通过 extension Schema，再发送给 Go server。

## DSD-002 宿主机身份

**决策：Accepted。**

| 字段 | 首选 | 兜底 | 不允许作为正常值 |
| --- | --- | --- | --- |
| `os` | 只读宿主机 `os-release` 的 `PRETTY_NAME` | NAME + VERSION；最后才是 platform | client 镜像发行版 ID |
| `cpu_model` | 宿主机 `lscpu` Model name | 宿主机 `/proc/cpuinfo` model name/hardware | 只有架构名或泛化 `unknown` |
| `cpu_cores` | 宿主机可见 logical CPUs | `os.cpu_count()` | 与容器 quota 混淆且未标记的值 |

CPU model 在 Go 原生 `servers[].cpu_model` 输出，避免同时维护两个长期字段。过渡期 Dashboard 可继续 `hardware.cpu_model ?? host.cpu_model`。

## DSD-003 原生资源口径

**决策：Proposed。** 继续沿用 ServerStatus wire 单位：内存 KiB、硬盘 MiB、uptime 秒、CPU 百分比；不把这些字段复制进 Hardware 扩展。

前置条件：

1. 物理机与 client 容器的内存总量在允许误差内一致。
2. `get_hdd()` 的 filesystem allowlist 能覆盖目标根盘，且不会把额外 bind mount 重复求和。
3. uptime 来自物理机 boot time，而不是容器启动时间。

若任一条件失败，应修 collector 可见性/挂载，不应在 WebUI 用预设值补偿。

## DSD-004 Hardware 所有权

**决策：Proposed。** Hardware 扩展使用统一 600 秒采集周期和一个 Python 所有者；psutil 每秒 update 只读取 last-good hardware snapshot，不再每秒执行 SMART。

| 数据 | 同一 hardware 周期行为 |
| --- | --- |
| CPU model | 进程启动读取并缓存，写入每轮快照 |
| CPU temperature | 每轮扫描 hwmon |
| SMART health/temp/hours/I/O | 每轮只执行一次 smartctl 文本和一次必要 JSON 命令 |
| `updated_at` | 本轮所有已请求 Hardware source 完成后写入 |
| partial failure | 保留仍有效值；error code 指明失败 source；不得伪造当前时间为 last-good 时间 |

选择统一周期的理由：当前 Dashboard/Web 刷新周期为 10 分钟，秒级 SMART 没有用户价值；统一时间也能在不修改现有合同结构的前提下给 `hardware.updated_at` 明确语义。

## DSD-005 SMART 解析

**决策：Proposed，设备证据完成前为 Blocked。**

优先级：

1. 健康：`smartctl -x` overall-health 文本。
2. 温度：Device Statistics `0x05/0x008`, `0x020`, `0x028`。
3. 通电小时：Device Statistics `0x01/0x010`。
4. 写入/读取：`0x01/0x018`, `0x028` 乘设备 logical sector size。
5. 只有主来源缺失时才使用 ATA/NVMe/SCSI 兼容字段，并设置 source 枚举。

规则：

- 不把命令字符串或 raw smartctl 输出写入 stats。
- smartctl 失败时 status 为 `unknown`，不是 `passed`。
- 不支持 Device Statistics 的设备允许相应字段为 null。
- logical sector size 无法确定时累计 I/O 为 null + `sector_size_unknown`，不得固定乘 512 猜测。

## DSD-006 Docker 来源与暴露

**决策：Accepted。**

- 数据源只允许 `GET /containers/json?all=1`；Release A 不调用 inspect、events 或写 API。
- collector 周期建议 60 秒，满足 120 秒 stale 阈值，不再每秒请求 Socket。
- running/total 从完整响应计算；数组限额只影响 `containers[]`，必须设置 `truncated`。
- 容器输出严格限定为 `names`、`image`、`status`、`ports`；不采集、不隐藏、不保留 `command`。
- error 只输出固定 code、source、retryable 和可选 HTTP status，不输出 Socket response 或 exception 原文。
- Docker Socket 仍按高权限依赖记录，不能因 mount 标记 `ro` 而降级风险。

`docker_volumes` 继续归属 Hermes config summary，不与 Docker 实际 Mounts 混为同一来源。

## DSD-007 Profile 注册

**决策：Accepted。** Profile 名称、目录、config、env 和 API 地址均由独立 collector 注册表驱动，不硬编码三个名称，也不加入 `server/config.json`。

优先级：

1. 注册表 Profile 显式字段。
2. Profile 专用环境变量，仅作部署覆盖。
3. 旧默认名称/端口只保留一个迁移周期，并有弃用诊断。

输出边界：

- Profile name 可进入 stats。
- `profile_dir`, `config_path`, `env_path`, API key 不进入 stats。
- API base URL 默认不进入 browser；诊断只输出 enabled/status/source enum。
- 一个 Profile 失败不能删除其他 Profile。

## DSD-008 Hermes 字段优先级

**决策：Deferred 到 Release B，但来源先固定。**

| 字段 | 首选 | 兜底 | error 条件 |
| --- | --- | --- | --- |
| service/API status | `GET /health` | 无 API 值时 service manager 仅作诊断 | 401、timeout、invalid JSON 分开 |
| gateway status | CLI Gateway Service status | user service state | CLI unavailable/parse failure |
| manager mode | CLI Gateway Service manager | null | CLI unavailable/parse failure |
| model/provider | CLI Environment | config/health 的明确字段 | 来源冲突时标记 diagnostic |
| usage mode | CLI 中与当前 Provider 匹配的 API Keys/Auth Providers | null | 不根据“存在任意 auth”猜当前模式 |
| auth refresh | 与当前 Provider 匹配且 logged-in 的 Refreshed | null | 格式无效/Provider 不匹配 |
| jobs | `GET /api/jobs` | CLI count | API error/列表截断 |
| sessions | 分页 `GET /api/sessions` | CLI count | 超页上限、has_more 未完成 |
| config summary | 显式 Profile `config.yaml` | 标准候选路径 | missing/parse failure |

Runs、聊天、stop、approval 不属于来源优先级，因为 1.0 没有交付这些能力。

## DSD-009 Token 语义

**决策：Accepted。** Token usage 是 diagnostic；只有来源和窗口可证明时才显示数字。

- 字段保持 `input_tokens`, `output_tokens`, `total_tokens`, `estimated`, `source`, `window_start`, `window_end`。
- API usage 的 endpoint 响应也不自动等于全局、日度或月度账本。
- 无稳定窗口时 window 为 null，UI 不显示“月度/总计”等账本措辞。
- 本地 logs/state 兜底必须 `estimated=true`。
- unavailable 时三项 token 都为 null；不使用 0 伪装无消耗。

## DSD-010 Freshness 与错误

**决策：Accepted。**

| 域 | collector 周期 | stale 阈值 | 时间所有者 |
| --- | --- | --- | --- |
| Hardware | 600 秒 | 900 秒 | collector |
| Docker | 60 秒 | 120 秒 | collector |
| Hermes | 600 秒 | 900 秒 | exporter |
| Profile | 600 秒 | 900 秒 | 每 Profile exporter |

服务端必须重新计算 stale；client 传入的 stale 只是提示。root `stats.updated` 与 `received_at` 不改变领域 `updated_at`。

错误采用 [STATS_CONTRACT.md](STATS_CONTRACT.md) 的结构化对象。最近采集失败时可保留 last-good 值和原时间，同时 error 非 null；不得用失败时刻刷新 `updated_at`。

## DSD-011 Wire 与兼容

**决策：Accepted。**

- 新 client 发送结构化 `hardware`, `docker`, `hermes`。
- Go 在过渡期读取旧 `hardware_json`, `docker_json`, `hermes_json`，解析后进入同一验证器。
- 同域新旧同时出现时新结构优先，不合并。
- legacy raw string 不进入 NodeState、stats、日志或 OpenAPI。
- 单域无效时保留基础 update，把该域降级为安全 error。
- 没有扩展的上游 client 继续正常连接并得到 not-reported 对象。

## DSD-012 Secret 边界

**决策：Accepted。** API key 只存在 client collector；Go server 和 browser 不接收 Hermes secret。

禁止输出：

- API key、refresh/session secret、Authorization 值。
- Profile env 原文、config 原始内容或密钥原值。
- 真实 Profile/config/env 路径。
- raw Docker response、raw exception、raw API response、raw smartctl output。
- legacy JSON string。

自由文本字段默认不允许；确需允许时必须有最大长度、字符策略和专用 sanitizer。日志使用 code/source/count/size，不记录 payload。

## DSD-013 Browser 边界

**决策：Accepted。** Browser 只请求 Go `/json/stats.json` 的脱敏字段，不直连 Docker Socket、Hermes API、collector 文件或宿主机命令。

- 当前单主机 Dashboard 继续保留。
- 顶栏可显示浏览器 fetch 时间，但必须与领域采集时间/陈旧状态区分。
- Profile 详情只消费 server allowlist；Release A 不输出 config summary 路径或 P1 明细。
- 不用 1.0 Web 文件覆盖 Go 2.0；已确认本地 Dashboard 增量实现作为 B3 基线。

## 待确认决策

| 项目 | 建议 | 所需证据 | 最晚确认点 |
| --- | --- | --- | --- |
| DSD-003 原生磁盘口径 | 只统计物理机根文件系统 | host/container `df` 与 psutil partitions 对照 | B1 开始前 |
| DSD-004 统一 hardware 600 秒 | 接受 | 目标 UI 对 CPU 温度实时性的确认 | B1 开始前 |
| DSD-005 扇区大小 | 动态读取 | smartctl information/JSON 脱敏证据 | SMART 实现前 |
| DSD-006 Docker 字段 | 四字段 allowlist | 无 | 已在 Release C 固化 |
| legacy 保留周期 | 一个完整发布周期 | 部署升级清单 | B2 合并前 |
| Profile/path 诊断 | 只在 client 本地日志显示脱敏 basename | 运维排障需求 | Release B 前 |

## 关联文档

- 事实来源：[DATA_SOURCE_MAP.md](DATA_SOURCE_MAP.md)
- 调用链：[SOURCE_TRACE.md](SOURCE_TRACE.md)
- 缺口：[DATA_GAP_REPORT.md](DATA_GAP_REPORT.md)
- 实施边界：[MILESTONE_B_PR_PLAN.md](MILESTONE_B_PR_PLAN.md)
