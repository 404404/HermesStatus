# HermesStatus Go 实施映射

## 目录

- [目的](#目的)
- [计划类型](#计划类型)
- [server/model.go](#servermodelgo)
- [server/tcp_server.go](#servertcp_servergo)
- [server/app.go](#serverappgo)
- [server/http_server.go](#serverhttp_servergo)
- [server/openapi.go](#serveropenapigo)
- [持久化与恢复](#持久化与恢复)
- [旧客户端兼容](#旧客户端兼容)
- [过渡策略](#过渡策略)
- [后续 PR 边界](#后续-pr-边界)
- [未决问题](#未决问题)
- [关联文档](#关联文档)

## 目的

本文把 [STATS_CONTRACT.md](STATS_CONTRACT.md) 映射到 Go 2.0 的现有文件。它只定义计划类型、验证点和 PR 边界，不包含业务实现代码。

## 计划类型

| 类型 | 计划字段 | 用途 |
| --- | --- | --- |
| `ExtensionStats` | `ExtensionVersion`, `Hardware`, `Docker`, `Hermes` | Agent update 中的结构化扩展根对象 |
| `ExtensionSnapshot` | `ExtensionStats`, `ReceivedAt` | stats 输出使用的服务端快照 |
| `HardwareStats` | CPU model/temp、disk temp/SMART/hours/read/write/device/source、freshness/error | HS-004 至 HS-008 |
| `TemperatureReading` | `Value`, `Unit`, `Source` | CPU 温度 |
| `DiskTemperatureStats` | `Current`, `Highest`, `Lowest`, `Unit`, `Source` | SMART 温度三值 |
| `DockerStats` | `Running`, `Total`, `Limit`, `Truncated`, `Containers`, freshness/error | HS-009 |
| `DockerContainerStats` | `Names`, `Image`, `Status`, `Ports` | Release C Docker 表格行 |
| `HermesStats` | `Profiles`, freshness/error | HS-010/HS-011 的稳定容器 |
| `HermesProfileStats` | Profile 身份、兼容状态字段、usage、allowlisted config summary、freshness/error | Profile 稳定外形；P1 字段 Release A 可为空 |
| `TokenUsageStats` | input/output/total/estimated/source/window | 仅固定诊断合同，不在 Release A 采集 |
| `ExtensionError` | code/message/source/retryable/http status | 结构化安全错误 |
| `SanitizedConfigSummary` | `DockerVolumes` | 仅为 fixture 和 1.0 兼容外形；Release A 不展示 |
| `legacyExtensionWire` | 三个旧 JSON string | TCP 过渡解析专用，不进入 NodeState |

所有字符串字段需要显式长度常量；所有数组需要显式最大数量常量。常量与 Schema 数值必须来自同一合同并由测试互相校验。

## server/model.go

计划修改：

1. 在 `AgentStats` 增加可选结构化 `Hardware`, `Docker`, `Hermes` 字段。
2. 定义上表中的扩展类型和 JSON tag。
3. 定义 `ValidateExtension()` 或等价纯函数，执行：
   - 必填/null/枚举检查。
   - 字符串长度、数组数量、数值范围检查。
   - `running <= total`、Token total/window 等跨字段约束。
   - 自由文本 secret 检测；Docker 容器对象采用四字段 allowlist，不接收 command。
   - RFC 3339 时间解析。
4. 不修改 `ServerConfig`、`RuntimeConfig` 或 collectionSpecs；扩展字段不进入 `server/config.json`。

验证返回值应区分“整个 update 无法解析”和“单扩展域无效”。后者生成安全 `ExtensionError`，不丢弃基础 AgentStats。

## server/tcp_server.go

计划修改：

1. TCP 行协议仍为 `update {JSON}`，保持原生客户端兼容。
2. 使用临时 wire 类型读取结构化扩展和旧 `*_json` 字符串。
3. 规范化顺序：结构化字段优先 -> 旧字符串按字节上限解析 -> 默认 not_reported 对象 -> 统一验证。
4. 旧字符串仅允许 JSON object；解析后立即释放，不传给日志、NodeState 或 stats。
5. 扩展验证失败时：
   - 接受并更新原生 CPU/内存/磁盘/网络字段。
   - 对失败域写入安全 degraded 对象。
   - 日志只记录 username、域、error code 和尺寸，不记录 payload。
6. 维持现有 1 MiB scanner 总上限，并增加扩展域/数组级上限。

## server/app.go

计划修改：

1. `NodeState.Stats` 随 `AgentStats` 保存已验证扩展结构；不保存 legacy raw strings。
2. `updateAgent()` 在接收时写 `ReceivedAt`，保留域的采集 `UpdatedAt`。
3. `snapshotStats()` 在构建每个 server map 时映射 `hardware`、`docker`、`hermes`。
4. 输出前根据当前服务端时间重算 stale，不信任 client 值。
5. 没有扩展的旧客户端输出稳定的空对象和 `not_reported` error，避免 Dashboard 对 undefined 做猜测。
6. stats 每秒刷新不得修改域级 `updated_at`。
7. reload/disconnect 后保留 NodeState 的现有 last-good 值仅到连接身份被替换；过阈值自动 stale。

## server/http_server.go

Release A 不新增 Hermes API 路由。

计划修改仅限：

- `/json/stats.json` 返回 `SnapshotStats()` 中的扩展对象。
- 继续设置 `Cache-Control: no-store` 和现有安全 header。
- 不增加 `/api/hermes/config-summary`。
- 不接收浏览器传入的 Hermes API Key，也不代理 Hermes API。
- HTTP JSON encoder 不应记录 response body。

## server/openapi.go

计划修改：

1. 为 `/json/stats.json` 的节点响应增加 Hardware/Docker/Hermes 扩展 Schema 引用。
2. 只描述白名单字段、nullability、限制和脱敏示例。
3. 不加入 API Key、password、Authorization、原始 `.env` 或 config.yaml 字段。
4. 不为 Release A 增加 Hermes operation；尤其不增加 summary、Runs、chat、stop 或 approval。
5. OpenAPI 示例使用 `testdata/migration` 同类脱敏值，不使用实际主机/IP/Profile 路径。

## 持久化与恢复

| 场景 | 行为 |
| --- | --- |
| 正常 stats 持久化 | 扩展对象随 `stats.json` 写入，便于静态检查和调试 |
| Go 进程重启 | 沿用 2.0 当前策略，仅恢复月流量基线；不把扩展恢复到 NodeState |
| 客户端尚未重连 | 输出稳定 not_reported 空对象，`updated_at:null`, `stale:true` |
| 客户端重连并上报 | 新 update 替换空对象，`received_at` 使用服务端时间 |
| stats 备份文件 | 可能包含脱敏扩展，但不作为 freshness 来源 |
| 损坏/旧 stats | 忽略扩展恢复错误，不阻止服务启动 |

不恢复扩展是有意选择：避免重启后把磁盘中的历史 SMART/Docker/Hermes 快照显示为新鲜数据。

## 旧客户端兼容

| 客户端行为 | Go 服务端策略 |
| --- | --- |
| 无扩展字段 | 基础指标正常接收；扩展输出 not_reported |
| 只发送 `hardware_json`/`docker_json`/`hermes_json` | 临时解析、同一 Schema 验证、转为结构化对象 |
| 同时发送结构化和旧字段 | 结构化字段优先；忽略对应旧字段 |
| 旧字段超限/不是对象 | 该域 degraded，基础 update 仍接受 |
| 结构化域有未知字段 | 该域拒绝并 degraded，未知值不透传 |
| 整行超过 1 MiB/JSON 损坏 | 沿用 Go 原生协议失败处理 |

## 过渡策略

1. `feature/go-extension-models` 引入结构类型、验证和 legacy wire parser，但客户端仍可发旧字段。
2. `feature/go-extension-pipeline` 打通 NodeState、Snapshot、持久化输出和 OpenAPI。
3. `feature/client-structured-payload` 修改 Python client 发送结构化字段；保留一个发布周期的服务端旧字段兼容。
4. 观察部署日志中的 legacy 使用计数；日志不得含 payload。
5. 所有已知客户端升级后，单独 PR 移除 legacy parser。移除前更新合同版本并提供迁移说明。

## 后续 PR 边界

| 分支/PR | 允许范围 | 明确不包含 | 主要验证 |
| --- | --- | --- | --- |
| `feature/go-extension-models` | `server/model.go` 类型、常量、验证、secret sanitizer、模型单测 | NodeState/HTTP/UI/client | Schema fixture 与 Go validation 一致 |
| `feature/go-extension-pipeline` | `server/tcp_server.go`, `server/app.go`, `server/http_server.go`, `server/openapi.go` 管线 | Python/Web/Compose | 旧/新 update、snapshot、restart、OpenAPI |
| `feature/client-structured-payload` | Python client/exporter 的结构化序列化和兼容测试 | Go UI、collector 重写 | 八类 fixture、payload size、无 secret |
| `feature/p0-dashboard` | 2.0 WebUI 内增量实现单主机 P0 Dashboard | P1 Profile 详情、整页覆盖 | 桌面/移动、空/降级/长值、三档色 |
| `feature/p0-compose` | Go server + Python client 两容器部署、挂载和启动验证 | 权限收敛、Go collector | 宿主机 OS/hwmon/SMART/Docker/状态目录 |

每个 PR 必须以 `2.0` 为基线，并引用本合同；不得在前一 PR 中提前实现后一 PR 的职责。

## 未决问题

1. P0 Dashboard 是否只显示第一个启用节点，还是在多节点配置时提供明确选择器？
2. hardware 单一 `updated_at` 是否足够表达秒级 CPU 温度与 600 秒 SMART 的不同 freshness？若不足，应在实现前拆分子时间戳并升级 Schema。
3. Docker 容器对象已在 Release C 固化为 `names/image/status/ports` 四字段，旧 command 不再是待决项。
4. `config_summary.docker_volumes` 是按 fixture 要求保留的兼容字段；Release A 是否只传输但不显示，需实现 PR 再确认。
5. legacy parser 保留几个版本或多少天后删除，需要部署升级计划。

## 关联文档

- 范围：[SCOPE_DECISIONS.md](SCOPE_DECISIONS.md)
- 合同：[STATS_CONTRACT.md](STATS_CONTRACT.md)
- Schema：[schema/agent-update-extension.schema.json](schema/agent-update-extension.schema.json)、[schema/stats-extension.schema.json](schema/stats-extension.schema.json)
- 迁移计划：[MIGRATION_PLAN.md](MIGRATION_PLAN.md)
