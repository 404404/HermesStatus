# HermesStatus 数据源映射

## 目录

- [审计口径](#审计口径)
- [状态定义](#状态定义)
- [ServerStatus 原生资源](#serverstatus-原生资源)
- [Hardware 数据域](#hardware-数据域)
- [Docker 数据域](#docker-数据域)
- [Hermes 数据域](#hermes-数据域)
- [凭证与部署边界](#凭证与部署边界)
- [刷新与缓存](#刷新与缓存)
- [验证命令映射](#验证命令映射)
- [未确认项](#未确认项)
- [关联文档](#关联文档)

## 审计口径

本文件把 `1.0` 的真实实现映射到 `2.0` Go 目标，不把合同草案当作已经存在的运行能力。

| 基线 | 审计对象 | 本次依据 |
| --- | --- | --- |
| `1.0` | C++ server、Python client/exporter、Docker Compose、WebUI | `hermesstatus/1.0`，提交 `36168a6` |
| `2.0` | Go server、上游 Python client、原生 Compose | `hermesstatus/2.0`，提交 `70d996e` |
| 已确认 Dashboard | 已部署但尚未推送的 P0 单主机界面 | 本地 `codex/p0-dashboard-shell`：提交 `2fce96b` 加 4 个未提交 Web 文件 |

提交前已成功执行 `git fetch hermesstatus 1.0 2.0`；`codex/data-source-map` 与最新 `hermesstatus/2.0` 均指向 `70d996e`，ahead/behind 为 `0/0`。1.0 与 2.0 的共同上游基点为 `e0aae47`。

本次重点覆盖 HS-004 至 HS-011、HS-021、HS-022、HS-023；Hermes P1 字段只记录 1.0 的实际来源，不计入 Release A 实现范围。

## 状态定义

| 状态 | 含义 |
| --- | --- |
| 已验证-代码 | 已沿调用链读到采集、上报和消费实现 |
| 已验证-测试 | 代码路径另有现有自动测试通过 |
| 待实机 | 代码路径明确，但设备、权限、输出格式或数值尚未在目标主机复核 |
| 缺失 | 2.0 当前没有采集或承载实现 |
| 丢弃 | 数据可到达入口，但在后续层被忽略 |
| 合同草案 | Schema/fixture 已定义，业务管线尚未实现 |

## ServerStatus 原生资源

| 功能 | 字段 | 1.0/2.0 主来源 | 采集位置 | 当前刷新 | 兜底与失败 | stats 输出 | 2.0 目标 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CPU 使用率 | `cpu` | psutil `cpu_percent()`；linux client 使用 `/proc/stat` 差值 | `clients/client-psutil.py:get_cpu`; `clients/client-linux.py:get_cpu` | client update 周期，默认 1 秒 | 采集异常会导致本轮 update 失败并重连 | `servers[].cpu`，Go 快照转为整数 | 保留原生字段；对照宿主机 `mpstat/top` | 已验证-代码，数值待实机 |
| CPU 核数 | `cpu_cores` | psutil logical CPU；linux client 统计 `/proc/stat` | 2.0 两个 client 的 `get_cpu_cores` | 建连时一次 | psutil/`os.cpu_count()` 兜底 | `servers[].cpu_cores` | 保留原生字段 | 已验证-代码 |
| 内存 | `memory_total`, `memory_used` | psutil `/proc/meminfo` 视图 | `get_memory` | 默认 1 秒 | 无领域 error；异常使本轮失败 | 单位 KiB | 保留原生字段，需确认容器看到宿主机值 | 已验证-代码，待实机 |
| 硬盘容量 | `hdd_total`, `hdd_used` | psutil 枚举允许的文件系统并求和 | `get_hdd` | 默认 1 秒 | 不支持的 fstype 会被跳过，可能得到 0 | 单位 MiB | 保留原生字段，需固定宿主机根挂载口径 | 已验证-代码，待实机 |
| 已运行时间 | `uptime` | `time.time() - psutil.boot_time()` 或 `/proc/uptime` | `get_uptime` | 默认 1 秒 | 无领域 error | client 发送秒；Go 输出中文字符串 | 保留原生字段 | 已验证-代码 |
| 系统信息 | `os` | 1.0 优先宿主机只读 `os-release` 的 `PRETTY_NAME`；2.0 只读容器内 `ID` | 1.0 `get_host_os_name`; 2.0 update loop | 1.0 每秒；2.0 每秒 | 1.0 回退容器文件和 `platform`; 2.0 回退 `linux` | `servers[].os` | HS-004：显式读取宿主机发行版 | 1.0 已验证；2.0 来源错误 |
| CPU 型号 | `cpu_model` / `hardware.cpu_model` | 1.0 `lscpu --json` 后回退 `/proc/cpuinfo`；2.0 psutil client 仅用 `platform.*` 推断 | 1.0 `get_cpu_model`; 2.0 `get_cpu_model` | 建连缓存或进程缓存 | 1.0 为 `unknown`；2.0 可能退化为厂商或架构 | 1.0 位于 `hardware`; 2.0 原生位于 server 节点 | HS-004：宿主机 `lscpu`/`cpuinfo`，保留原生 `cpu_model` | 字段存在，2.0 来源不可靠 |

注意：`pid: host` 不等于共享宿主机 mount namespace。内存与磁盘容量是否与物理机一致必须由 [验证命令映射](#验证命令映射) 的主机/容器双侧结果确认。

## Hardware 数据域

| HS | 字段 | 权威来源与解析 | 1.0 采集/刷新 | 兜底 | 失败输出 | 1.0 输出链 | 2.0 目标 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HS-004 | `cpu_model` | `lscpu --json` 的 Model name；回退 `/proc/cpuinfo` | client 进程缓存；每次 update 复用 | `unknown` | 字符串 `unknown` | `hardware_json` -> C++ -> `servers[].hardware.cpu_model` | 使用原生 `servers[].cpu_model`；扩展可过渡兼容 | 已验证-代码，待实机值 |
| HS-005 | `cpu_temperature.value` | `/sys/class/hwmon/hwmon*/temp*_input` | client 每个 update 都扫描，默认 1 秒 | 关键词匹配失败时取第一个传感器 | `null` | 同上 | Python collector 采集，结构化 `hardware.cpu_temperature` | 已验证-代码，传感器映射待实机 |
| HS-005 | `cpu_temperature.unit` | collector 常量 `C` | 同 CPU 温度 | 无 | 温度为空时整个对象 `null` | 同上 | 常量并由 Schema 限制 | 已验证-代码 |
| HS-005 | `cpu_temperature.source` | hwmon chip + label | 同 CPU 温度 | hwmon 目录名 | `null` | 同上 | 限长、仅输出标签 | 已验证-代码，待实机 |
| HS-006 | `disk_smart_status` | `smartctl -x` 文本 `SMART overall-health...PASSED/FAILED` | exporter 默认 600 秒；client 又在每秒 update 执行一次 | SMART JSON status、通用 health 字段、SCSI grown defects | `unknown`；1.0 无结构化 error | exporter `hardware.json` 优先覆盖 client fallback | 单一 SMART 所有者；`unknown` + 安全 error | 已验证-代码，结果待实机 |
| HS-007 | `disk_temperature.current` | Device Statistics `0x05/0x008` | exporter 600 秒且 client 每秒重复 | 属性 194、SMART JSON、disk hwmon | `null` | `hardware.json`/client merge -> stats | 统一 600 秒 hardware 周期 | 已验证-代码，待实机 |
| HS-007 | `disk_temperature.highest` | Device Statistics `0x05/0x020` | 同上 | 无稳定兜底 | `null` | 同上 | 同上 | 已验证-代码，待实机 |
| HS-007 | `disk_temperature.lowest` | Device Statistics `0x05/0x028` | 同上 | 无稳定兜底 | `null` | 同上 | 同上 | 已验证-代码，待实机 |
| HS-007 | `disk_temperature.unit/source` | 常量 `C`；所选设备标签 | 同上 | SMART/hwmon 标签 | 对象空或 source 为 `null` | 同上 | 限长固定标签，不输出命令 | 已验证-代码 |
| HS-008 | `disk_power_on_hours` | Device Statistics `0x01/0x010` | exporter 600 秒且 client 每秒重复 | ATA 属性 9、SMART JSON power-on time | `null` | 同上 | 单一 SMART 所有者 | 已验证-代码，待实机 |
| HS-008 | `disk_written_bytes` | `0x01/0x018` Logical Sectors Written × 512 | 同上 | ATA 241、NVMe data units、SCSI counters | `null` | 同上 | 应读取逻辑扇区大小，不能永久假设 512 | 代码已验证；换算口径待确认 |
| HS-008 | `disk_read_bytes` | `0x01/0x028` Logical Sectors Read × 512 | 同上 | 无 | `null` | 同上 | 同上 | 代码已验证；换算口径待确认 |
| HS-006 | `disk_device` | `SMART_DEVICE` 或 `smartctl --scan` | 每轮 SMART 采集 | psutil 分区与设备 glob | `null` | 浏览器可收到 | 配置化并限制为设备路径 | 已验证-代码，设备待实机 |
| HS-006 | `disk_smart_source` | 1.0 保存完整执行命令字符串 | 每轮 SMART 采集 | JSON 命令 | `null` | 浏览器可收到 | 只输出固定枚举，不输出命令行 | 已验证-代码；1.0 存在披露风险 |
| HS-011 | `hardware.updated_at` | exporter 完成时间 | 仅 exporter 快照有值，默认 600 秒 | client 直接采集结果本身不生成时间 | exporter 缺失时字段缺失 | 由 `hardware.json` merge 进入 stats | 必填可空；服务端重算 stale | 已验证-代码；语义不完整 |
| HS-011 | `hardware.stale/error` | 1.0 不存在 | 不适用 | 不适用 | 不适用 | 不存在 | 按 [STATS_CONTRACT.md](STATS_CONTRACT.md) 实现 | 合同草案 |

1.0 的 `_merge_hardware()` 让 exporter 的非空值覆盖 client 的实时 fallback，并阻止 `unknown` 覆盖已有 passed/failed。它没有字段级时间，因此混合后的对象无法证明每个值来自同一次采集。

## Docker 数据域

| HS | 字段 | 权威来源 | 1.0 采集/刷新 | 限额/兜底 | 失败输出 | 1.0 输出链 | 2.0 目标 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HS-009 | `running` | Docker Engine `GET /containers/json?all=1`, `State == running` | client 每个 update，默认 1 秒 | 无缓存 | `0` + 原始异常文本 | `docker_json` -> C++ -> stats | Python collector 结构化上报 | 已验证-代码，待与 `docker ps` 比对 |
| HS-009 | `total` | 返回数组长度 | 同上 | 无 | `0` + error | 同上 | 同上 | 已验证-代码，待实机 |
| HS-009 | `limit` | `DOCKER_CONTAINER_LIMIT` | 进程启动读取 | `0` 表示全部 | 失败对象当前缺该字段 | 同上 | 类型化配置与上限 | 已验证-代码 |
| HS-009 | `truncated` | `len(rows) > len(containers)` 或 JSON 字节裁剪 | 每轮 | `DOCKER_JSON_MAX_BYTES` 默认 12000；从尾部删行 | 极端情况下退回空对象 | 同上 | 数量上限 + payload 上限 | 已验证-测试 |
| HS-009 | `error` | Python 异常 `str(e)` | 失败时 | 无脱敏 | 自由文本进入 stats | 同上 | 结构化 code/source/retryable | 已验证-代码；需修安全边界 |
| HS-009 | `containers[].id` | Docker `Id` 前 12 字符 | 每轮 | 最长 16 | 行被裁掉 | 同上 | 最长 64，UI 可显示短值 | 已验证-代码 |
| HS-009 | `containers[].names` | `Names` 去前导 `/` 后拼接 | 每轮 | 1.0 截断 120 字符 | `""` | 同上 | 最长 256 | 已验证-代码 |
| HS-009 | `containers[].state` | Docker `State` | 每轮 | 无 | `""` | 同上 | 枚举 + `unknown` | 已验证-代码 |
| HS-009 | `containers[].status` | Docker `Status` | 每轮 | 80 字符 | `""` | 同上 | 128 字符 | 已验证-代码 |
| HS-009 | `containers[].created` | Docker epoch 转相对英文时间 | 每轮 | 解析失败 `-` | `-` | 同上 | 建议传 epoch/RFC3339，由 UI 格式化 | 已验证-代码；目标格式待决策 |
| HS-009 | `containers[].image` | Docker `Image` | 每轮 | 80 字符 | `""` | 同上 | 256 字符 | 已验证-代码 |
| HS-009 | `containers[].command` | Docker `Command` | 每轮 | 仅截断 96 字符 | 可能含敏感参数 | 同上 | 默认隐藏或先脱敏；日志禁止 | 已验证-代码；安全阻断 |
| HS-009 | `containers[].ports` | Docker `Ports` 格式化 | 每轮 | 120 字符 | `-` | 同上 | 512 字符 | 已验证-代码 |
| HS-011 | `docker.updated_at/stale` | 1.0 不存在 | 不适用 | 不适用 | 不适用 | 不存在 | collector 时间 + 服务端 stale | 合同草案 |

Docker Socket 的 `:ro` bind mount 只限制挂载点文件系统语义，不把 Docker API 变成只读。持有该 Socket 的进程理论上仍可调用高权限 Engine API；当前代码只实现一个 GET allowlist，但部署风险仍按高权限处理。

## Hermes 数据域

### Profile 注册和 Release A 外形

| HS | 字段/配置 | 1.0 来源 | 刷新 | 兜底/失败 | 最终输出 | 2.0 目标 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HS-010 | `profiles[].profile` | exporter 注册表 `profiles[].name` | 进程启动加载；快照 600 秒 | 无注册表时旧默认名称列表 | client 每秒读取每 Profile JSON | 独立 collector 配置，不进入 `server/config.json` | 已验证-测试 |
| HS-010 | `profile_dir` | `profiles[].profile_dir` | 进程启动 | `<hermes-root>/<profile>` | 不直接作为合同字段；1.0 `note` 可能泄露 | 仅采集侧配置 | 已验证-测试 |
| HS-010 | `config_path` | `profiles[].config_path` | 进程启动 | Profile 标准候选路径 | `config_summary.config_path` 在 1.0 可进入浏览器 | 仅采集侧；stats 禁止真实路径 | 已验证-测试；1.0 披露风险 |
| HS-010 | `env_path` | `profiles[].env_path` | 首次读取后进程缓存 | Profile 目录 `.env` | 原文不输出 | 仅采集侧 secret source | 已验证-代码 |
| HS-010/021 | `api.base_url` | 注册表、Profile 环境、动态环境变量 | exporter 每轮使用；配置在进程启动加载 | 通配监听地址改为 loopback；旧端口表 | 1.0 `api_base_url` 进入 Profile stats | 仅采集诊断，不给浏览器 | 已验证-测试 |
| HS-021 | API token | 动态环境变量、注册表或 Profile 环境 | 进程内按请求读取/缓存 Profile env | 缺失则不请求 | 只放请求 header，不应进入快照 | 只存在 client collector | 已验证-测试 |
| HS-011 | `hermes.profiles[]` | exporter 原子写入 Profile JSON；client 扫描状态目录 | exporter 600 秒，client 每秒读取 | 文件损坏/单文件异常时跳过 | `hermes_json` -> C++ -> stats | 结构化 Profile 数组 | 已验证-代码 |
| HS-011 | `hermes.updated_at/stale/error` | 1.0 不存在 | 不适用 | 失败时 client root `error` 可能是自由文本 | 更新时间未进入最终 stats | 领域时间 + 结构化 error | 合同草案 |
| HS-011 | `profiles[].updated_at/stale/error` | 1.0 不存在 | 不适用 | `note` 混合 API 错误和本地路径 | 无稳定时间 | Profile 独立时间与 error | 合同草案 |

### 1.0 Hermes P1 字段真实来源

这些字段用于后续 Release B 设计；本次不实现。

| 字段 | P0/P1 | 1.0 首选来源 | 兜底 | 最终 stats 情况 |
| --- | --- | --- | --- | --- |
| `service_status`, `api_status` | P1 | `GET /health` 的 status/state/health | CLI/service manager | client 选择后输出 |
| `gateway_service`, `manager_mode` | P1 | `hermes -p <profile> status` 的 Gateway Service | user service 状态 | 输出 |
| `model`, `provider` | P1 | CLI Environment | 本地文件/health provider | 输出 |
| `usage_mode`, `auth_refreshed_at` | P1 | CLI API Keys/Auth Providers | 无 | 输出 |
| `scheduled_jobs_active/total` | P1 | `GET /api/jobs` 返回的有限列表 | CLI Scheduled Jobs | 输出；API 列表被 `MAX_TABLE_ROWS` 截断时总数可能偏小 |
| `sessions_active/total/has_more` | P1 | 分页 `GET /api/sessions` | CLI Sessions | 输出 |
| `usage` | P1/diagnostic | jobs + 全分页 sessions payload 的递归 usage | detailed health、health、本地昨日日志 | 输出；无稳定窗口；无值时伪装为 0 是已知缺口 |
| `agent_version` | P1 | `hermes --version`，进程缓存 | host namespace CLI | 输出 |
| `config_summary` | P1 | 脱敏投影 Profile `config.yaml` | 候选路径 | 输出；包含路径和挂载点 |
| `mixture_of_agents` | P2 | `GET /v1/toolsets` | unavailable 对象 | 输出 |
| `jobs`, `sessions`, `capabilities` | P1/P2 | Hermes API | 无 | exporter 快照有；client 明确裁掉，最终 stats 不存在 |
| `runs` | 非现有能力 | 无，固定空数组 | 无 | exporter 快照空；不能视为已交付 |

## 凭证与部署边界

| HS | 边界 | 1.0 实现 | 风险/失败 | 2.0 决策 | 状态 |
| --- | --- | --- | --- | --- | --- |
| HS-021 | Hermes API key 只在 client | exporter 读取环境/`.env`，请求时构造 Authorization | Profile 环境被进程缓存；不得打印 | 保持；Go server/Web 永不接收 | 已验证-测试 |
| HS-021 | 响应白名单 | exporter 选择字段；config summary 选择固定结构 | Docker command、error/note、路径仍可能披露 | Schema 白名单 + 自由文本脱敏 | 部分实现，存在阻断 |
| HS-022 | wire 上限 | C++ 64 KiB；hardware 4 KiB、Docker/Hermes 各 32 KiB；client 另做字节裁剪 | 超限静默退回空对象 | Go 全局 1 MiB + 域/数组/字符串限额 | 1.0 已验证-测试；2.0 缺失 |
| HS-022 | 扩展传输 | 三个 JSON-in-string 字段 | C++ 不做结构验证，直接嵌入 stats | 结构化对象；旧字段短期兼容 | 1.0 已验证；2.0 在反序列化处丢弃 |
| HS-023 | host network | 访问 loopback Hermes API | 扩大网络可见范围 | 首阶段保留 | 已验证-代码 |
| HS-023 | host PID + `nsenter` | 容器内 CLI 不可用时进入宿主机 | 高权限；依赖 PID 1 与宿主机用户 | 仅 CLI 兜底保留 | 已验证-代码，待实机 |
| HS-023 | privileged + `/dev` | 允许 SMART | 权限过宽 | 首阶段验证，后续最小化 | 已验证-代码，待实机 |
| HS-023 | hwmon/OS/Docker/Profile/status 挂载 | 提供物理机数据和快照交换 | Socket 与路径披露风险 | 明确只读/读写边界 | 已验证-代码，待实机 |

## 刷新与缓存

| 数据 | 1.0 实际频率 | 当前缓存 | 当前时间戳 | 目标建议 |
| --- | --- | --- | --- | --- |
| CPU/内存/硬盘/uptime | 默认 1 秒 | CPU 型号进程缓存 | root stats `updated` 每次写入 | 保持原生 update |
| CPU 温度 | 默认 1 秒 | 无 | 只有与 exporter hardware 合并时才可能有 `updated_at` | 统一 hardware 600 秒周期或单独时间戳；见决策文档 |
| SMART | exporter 600 秒，同时 client 默认每秒重复执行 | `hardware.json` 是 last-good 风格 | exporter `updated_at` | 移除重复所有权；只由 600 秒 collector 执行 |
| Docker | 默认 1 秒 | 无 | 无领域时间 | 60 秒采集，`updated_at` + 120 秒 stale |
| Hermes API/CLI/config | exporter 600 秒 | env/version/注册表进程缓存 | Profile 没有 `updated_at` | 600 秒，每域/Profile 独立时间 |
| Web | 1.0 与已确认 Dashboard 均 10 分钟，支持手动刷新 | 失败时保留上次文档 | 当前 UI 显示浏览器成功 fetch 时间 | 后端领域时间用于新鲜度；浏览器 fetch 时间只作 UI 元信息 |

## 验证命令映射

所有命令使用占位符，不应把真实密钥、内网地址或真实 Profile 路径写入报告。命令执行位置分为物理机与 client 容器。

| 数据点 | 物理机命令 | client 容器命令 | 期望字段 | 失败分类 |
| --- | --- | --- | --- | --- |
| CPU 使用率/核数 | `mpstat 1 2`；`nproc` | `python3 -c 'import psutil; print(psutil.cpu_percent(1), psutil.cpu_count())'` | `cpu`, `cpu_cores` | `SOURCE_ABSENT`, `VALUE_MISMATCH` |
| 内存 | `free -b` | `python3 -c 'import psutil; print(psutil.virtual_memory())'` | `memory_total`, `memory_used` | `NAMESPACE_MISMATCH`, `VALUE_MISMATCH` |
| 根盘容量 | `df -B1 /` | `python3 -c 'import psutil; print(psutil.disk_partitions()); print(psutil.disk_usage("/"))'` | `hdd_total`, `hdd_used` | `MOUNT_MISMATCH`, `FSTYPE_FILTERED` |
| uptime | `cut -d. -f1 /proc/uptime` | `python3 -c 'import psutil,time; print(int(time.time()-psutil.boot_time()))'` | `uptime` | `NAMESPACE_MISMATCH` |
| OS | `sed -n '1,20p' /etc/os-release` | `sed -n '1,20p' /host/etc/os-release` | `os` 为宿主机 `PRETTY_NAME` | `MOUNT_MISSING`, `PARSE_ERROR` |
| CPU 型号 | `LC_ALL=C lscpu` | `LC_ALL=C lscpu --json`; `sed -n '1,40p' /proc/cpuinfo` | `cpu_model` 为物理机型号 | `TOOL_MISSING`, `GENERIC_VALUE` |
| CPU 温度 | `find /sys/class/hwmon -maxdepth 2 -name 'temp*_input' -print` | 同一只读路径检查 | `cpu_temperature.value/source` | `MOUNT_MISSING`, `SENSOR_UNMATCHED` |
| SMART 全量 | `sudo smartctl -x <smart-device>` | `smartctl -x <smart-device>` | overall-health、Device Statistics 三组偏移 | `PERMISSION`, `DEVICE_MISSING`, `OUTPUT_UNSUPPORTED`, `PARSE_ERROR` |
| Docker 汇总 | `docker ps -a --format '{{.ID}}\t{{.Names}}\t{{.State}}\t{{.Image}}'` | 对 Unix Socket 执行 `GET /containers/json?all=1` 的只读审计脚本 | running/total 与容器行一致 | `SOCKET_MISSING`, `PERMISSION`, `HTTP_ERROR`, `PARSE_ERROR` |
| Profile 注册 | 检查 collector 注册表的脱敏摘要 | `python3 /app/export-hermes-status.py` 后用 `python3 -m json.tool <status-file>` | Profile 名称集合和每 Profile 快照 | `CONFIG_MISSING`, `PATH_MISSING`, `WRITE_ERROR` |
| Hermes CLI | `hermes -p <profile> status` | 容器内 CLI；失败时验证 host namespace 兜底 | gateway/model/provider/jobs/sessions | `TOOL_MISSING`, `NSENTER_FAILED`, `PARSE_ERROR` |
| Hermes health | 使用环境中的密钥变量请求 `<loopback-base>/health`，只输出 HTTP 状态码和脱敏 JSON 字段名 | 同网络 namespace 请求 | `service_status`, `api_status` | `DISABLED`, `AUTH`, `TIMEOUT`, `HTTP_ERROR`, `PARSE_ERROR` |
| wire | 捕获 client 构造对象的键名/字节数，不输出值 | 运行 payload limit 测试 | 三个域均不超限 | `LIMIT`, `SERIALIZE_ERROR` |
| Go 接收 | 发送脱敏 fixture update | 查询 `/json/stats.json` | 扩展对象仍存在且字段一致 | `UNMARSHAL_DROP`, `VALIDATION`, `SNAPSHOT_LOSS` |
| Browser | 不使用真实环境参数；仅访问脱敏 fixture 或 stats | 不适用 | 卡片/表格与 stats 一致 | `UI_MAPPING`, `STALE_DISPLAY` |

统一失败分类：

- `SOURCE_ABSENT`：宿主机本身没有数据源。
- `MOUNT_MISSING` / `NAMESPACE_MISMATCH`：宿主机有数据但容器不可见或看到不同命名空间。
- `PERMISSION`：设备、Socket 或 namespace 权限不足。
- `PARSE_ERROR` / `OUTPUT_UNSUPPORTED`：命令成功但输出不符合解析假设。
- `AUTH` / `TIMEOUT` / `HTTP_ERROR`：Hermes 或 Docker API 传输失败。
- `LIMIT`：数组、字符串或总 payload 被裁剪/拒绝。
- `UNMARSHAL_DROP` / `SNAPSHOT_LOSS`：采集成功但在 server 管线丢失。
- `STALE_DISPLAY`：旧数据被当成最新数据展示。

## 未确认项

1. 目标主机当前 `lscpu`、hwmon chip/label、SMART Device Statistics 是否与 1.0 正则完全匹配。
2. 目标磁盘逻辑扇区大小是否始终为 512 字节；2.0 不应以设备样例替代通用规则。
3. client 容器的内存、根盘容量和 uptime 是否与物理机命令在允许误差内一致。
4. Docker Engine API 版本和长 command/image/ports 的实机最大值。
5. Profile 注册表、状态目录与 API 开关在新环境中的最终脱敏配置。
6. Hermes API 各 endpoint 的当前分页、usage 和 error JSON 形状。

## 关联文档

- 端到端路径：[SOURCE_TRACE.md](SOURCE_TRACE.md)
- 缺口与阻断：[DATA_GAP_REPORT.md](DATA_GAP_REPORT.md)
- 来源决策：[DATA_SOURCE_DECISIONS.md](DATA_SOURCE_DECISIONS.md)
- 后续 PR：[MILESTONE_B_PR_PLAN.md](MILESTONE_B_PR_PLAN.md)
- 数据合同：[STATS_CONTRACT.md](STATS_CONTRACT.md)
