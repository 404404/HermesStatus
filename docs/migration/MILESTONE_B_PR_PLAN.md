# HermesStatus Milestone B PR 计划

## 目录

- [目标](#目标)
- [前置门](#前置门)
- [PR 总览](#pr-总览)
- [B1 Go 扩展模型](#b1-go-扩展模型)
- [B2 Go 扩展管线](#b2-go-扩展管线)
- [B3 Client 宿主机数据](#b3-client-宿主机数据)
- [B4 Hermes Exporter 迁移](#b4-hermes-exporter-迁移)
- [B5 Compose 宿主机访问](#b5-compose-宿主机访问)
- [B6 真实数据集成](#b6-真实数据集成)
- [共同测试矩阵](#共同测试矩阵)
- [顺序与回滚](#顺序与回滚)
- [明确不包含](#明确不包含)
- [未决问题](#未决问题)
- [关联文档](#关联文档)

## 目标

Milestone B 把 B0 固化的数据来源和合同拆成六个可独立验证、可独立回滚的 PR。每个 PR 只处理一个主要失败面；B0 仍是文档阶段，本文件不授权提前实现业务代码。

已由用户确认并部署、但尚未推送的 P0 Dashboard 壳层必须先整理为独立 UI PR。它是 B6 的输入，不得夹入 B1 至 B5，也不得夹入本次 B0 文档 PR。

## 前置门

| 门 | 必须满足 | 未满足时 |
| --- | --- | --- |
| B0 文档 | source、trace、gap、decision、PR plan 经确认 | 不创建业务分支 |
| 远端基线 | 每个 PR 开始前 fetch 最新 `1.0`/`2.0` | 不基于过期引用实施 |
| 合同一致 | Schema、fixture、Go/Python 限额一致 | 不合并 B1/B3/B4 |
| 实机来源 | host/client 的 OS、CPU、hwmon、SMART、Docker 脱敏证据 | B3/B5 不合并 |
| 安全决策 | command、路径、raw error、legacy raw 的处理已确认 | 不让真实扩展进入 stats/browser |
| Hermes 范围 | Release A 与 Release B 的 Profile 字段边界明确 | B4 不开始 P1/P2 实现 |

## PR 总览

| 顺序 | 分支 | 输入 | 输出 | 依赖 | HS | 可独立回滚 |
| --- | --- | --- | --- | --- | --- | --- |
| B1 | `feature/go-extension-models` | Schema、fixture、B0 决策 | Go 扩展类型、验证器、legacy 解析模型 | B0 | HS-004 至 HS-011、HS-021、HS-022 | 是 |
| B2 | `feature/go-extension-pipeline` | B1 类型与 fixture | TCP -> NodeState -> Snapshot -> stats/OpenAPI | B1 | HS-010、HS-011、HS-021、HS-022 | 是 |
| B3 | `feature/client-host-data` | 1.0 host/SMART/Docker 实现、实机证据 | 结构化 OS/CPU/Hardware/Docker update | B1；对接验证依赖 B2 | HS-004 至 HS-009、HS-011、HS-022 | 是 |
| B4 | `feature/hermes-exporter-port` | 1.0 registry/exporter/config summary/API/CLI 行为 | Profile 快照和结构化 Hermes update | B1/B2；P1/P2 范围门 | HS-010、HS-011、HS-021、HS-022 | 是 |
| B5 | `feature/compose-host-access` | B3/B4 运行要求 | 最小化 host network/mount/device/socket/status 访问 | B3/B4 | HS-004 至 HS-011、HS-023 | 是 |
| B6 | `feature/real-data-integration` | B2 至 B5、已确认 Dashboard 壳层 | 双跑证据、真实 stats、关闭 fixture-only 路径 | B2/B3/B4/B5 + UI PR | HS-004 至 HS-011、HS-021 至 HS-023 | 是 |

B4 只规划 1.0 已存在的数据行为。Runs、聊天、停止、审批不是 B4 输入；是否在 Release A 之后启用 jobs/sessions/token/config summary/MoA，必须先通过范围门，不得借“迁移 exporter”扩张功能。

## B1 Go 扩展模型

### 合同

| 项 | 内容 |
| --- | --- |
| 允许修改 | `server/model.go`、纯模型/验证辅助文件、`server/*_test.go`；必要时同步 `docs/migration/schema/**` 与 `testdata/migration/**` |
| 禁止修改 | `server/tcp_server.go`、`server/app.go`、HTTP handler、Python client/exporter、Web、Compose、`server/config.json` |
| 输入 | `STATS_CONTRACT.md`、两份 JSON Schema、8 个 fixture、`DATA_SOURCE_DECISIONS.md` |
| 输出 | `ExtensionStats`、`HardwareStats`、`DockerStats`、`DockerContainerStats`、Release A `HermesStats/ProfileStats`、temperature/usage/error 类型、validation constants、`legacyExtensionWire` |
| 依赖 | B0 文档已确认，无代码 PR 依赖 |
| HS | HS-004 至 HS-011、HS-021、HS-022 |
| 回滚 | 整体回退 B1 commit；因未接 TCP/HTTP，不影响运行协议 |

### 验收标准

1. normal/empty/degraded/long-values fixture 与 Go validator 结果一致。
2. 字符串、数组、嵌套对象和域 payload 上限与 Schema 一致。
3. 未知字段、secret-like 字段、invalid timestamp、`running > total`、无窗口 Token 均有确定行为。
4. Docker command 使用已确认的 hidden/sanitized 规则；验证失败日志不含原值。
5. 不修改 `ServerConfig`、management API、TCP、stats 或 Web 行为。
6. Go unit tests 与静态检查通过。

## B2 Go 扩展管线

### 合同

| 项 | 内容 |
| --- | --- |
| 允许修改 | `server/tcp_server.go`、`server/app.go`、`server/http_server.go`、`server/openapi.go`、对应 `server/*_test.go` |
| 禁止修改 | Python client/exporter、Web、Dockerfile/Compose、management config schema、Hermes API 调用 |
| 输入 | B1 结构化扩展类型、`legacyExtensionWire`、normal/degraded/long fixture update |
| 输出 | structured/legacy decode、单域降级、NodeState 保存、Snapshot 映射、`/json/stats.json` 扩展、只读 OpenAPI 描述 |
| 依赖 | B1 |
| HS | HS-010、HS-011、HS-021、HS-022 |
| 回滚 | 回退 B2 后 server 恢复只处理原生字段；B1 未接线类型可保留或单独回退 |

### 验收标准

1. structured update 在 NodeState、Snapshot 和 stats 中语义一致。
2. legacy 三个 `*_json` 可受限解析；新旧同域并存时 structured 优先，raw string 不进入日志/stats。
3. 一个扩展域无效时，基础 update 和其他有效域仍更新。
4. 上游无扩展 client 继续工作，扩展状态明确为 not-reported。
5. 服务端按 received/domain time 重算 stale；root `updated` 不伪装领域新鲜度。
6. restart 不把持久化扩展恢复成新鲜 NodeState。
7. OpenAPI 只含白名单字段与脱敏示例。

## B3 Client 宿主机数据

### 合同

| 项 | 内容 |
| --- | --- |
| 允许修改 | `clients/client-psutil.py`、必要的只读 collector helper、client tests、脱敏 SMART/Docker fixture、client entrypoint 中与 host collector 生命周期直接相关的部分 |
| 禁止修改 | Go server、Web、正式 Compose、Hermes P1/P2 API/CLI/jobs/sessions/token/config summary、每秒 `smartctl` |
| 输入 | 1.0 的 `get_host_os_name()`、`get_cpu_model()`、hwmon/SMART/Docker 解析；B0 host/client 验证命令；B1 Schema |
| 输出 | 宿主机 OS/CPU model、600 秒 Hardware/SMART、受限 Docker 列表及领域时间/error 的 structured update |
| 依赖 | B1；与真实 Go server 联调依赖 B2 |
| HS | HS-004 至 HS-009、HS-011、HS-022 |
| 回滚 | 切回原生 2.0 client 镜像/entrypoint；Go server 继续接受无扩展 client |

### 验收标准

1. host/client 的 OS、CPU model、内存、根盘、uptime 按验证矩阵对照。
2. hwmon normal/empty/multiple 与 smartctl text/JSON/passed/failed/missing fixture 均通过。
3. SMART 只有一个 600 秒所有者；不再由每秒 update 重复调用。
4. Logical Sectors 使用已验证 sector size；未知时返回 null/error，不猜测。
5. Docker count 与 `docker ps -a` 一致，列表截断保留真实 total，command/error 不泄密。
6. normal/empty/degraded/long update 通过 Schema、字节上限和 secret scan。
7. 无 Web 依赖即可从 Go stats 验证结构化值未丢失。

## B4 Hermes Exporter 迁移

### 合同

| 项 | 内容 |
| --- | --- |
| 允许修改 | `scripts/export-hermes-status.py`、`scripts/hermes_config_summary.py`、Hermes collector registry/config parser、client Profile snapshot reader、entrypoint lifecycle、对应 tests/fixtures |
| 禁止修改 | Go server、Web、Compose、Runs/聊天/停止/审批、新 Hermes endpoint、secret 输出、Profile 配置原文透传 |
| 输入 | 1.0 registry、API/CLI/local fallback、原子快照、config summary 真实调用链；B1/B2 contract/pipeline |
| 输出 | 动态 Profile 注册、600 秒原子快照、service/gateway/API/model/provider/jobs/sessions/diagnostic usage/config summary/volumes/MoA 的白名单结构化 update，以及 Profile 级 time/stale/error |
| 依赖 | B1、B2；P1/P2 范围门明确后才能实现对应字段 |
| HS | HS-010、HS-011、HS-021、HS-022 |
| 回滚 | 停用 exporter lifecycle 并回退 client Profile reader；基础/Hardware/Docker update 不受影响 |

### 验收标准

1. Profile 名称、目录、config/env/API 地址全部来自 collector registry；无 `hermes1/2/3` 强制假设。
2. `0.0.0.0`/`::` 只在 client 内归一为 loopback；API key 只进入请求 header。
3. `/health`、detailed health、jobs、sessions 分页及 capabilities 的现有优先级由 fixture 固定；不添加新 endpoint。
4. CLI status、`nsenter`、本地日志 fallback 保持 1.0 语义或在决策文档标记差异。
5. Token 只有稳定窗口时才展示为窗口统计；否则 nullable/diagnostic + `estimated/source/window`，不伪装全局/月度账本。
6. config summary、docker volumes、MoA 只输出白名单；路径、密钥、原始 `.env`、raw response/error 不进入快照/stats。
7. 0/1/many/missing/corrupt/unauthorized/timeout/invalid JSON Profile 相互隔离。

## B5 Compose 宿主机访问

### 合同

| 项 | 内容 |
| --- | --- |
| 允许修改 | 2.0 client/server Dockerfile、Compose/override/env example、必要的 systemd 启动单元和部署文档；只包含 B3/B4 已证明需要的访问 |
| 禁止修改 | Go/Python/Web 业务逻辑、真实 secret、真实用户路径/私网地址、`server/config.json` Hermes 扩展 schema |
| 输入 | B3/B4 所需 host OS、hwmon、SMART device、Docker Socket、Hermes root/status、host network/PID 的最小权限清单 |
| 输出 | Go server + Python client 两容器部署；只读/读写 mount、device/capability、healthcheck、自启动和回滚配置 |
| 依赖 | B3、B4 的实机访问证据 |
| HS | HS-004 至 HS-011、HS-023 |
| 回滚 | 使用独立 Compose project/端口/状态目录；停止 2.0 并恢复 1.0，不改 Profile 配置或 secret |

### 验收标准

1. `docker compose config` 成功，输出报告经脱敏且无意外 secret。
2. host/client 命令证明 OS、hwmon、SMART device、Docker Socket、Profile/status 可见性与权限符合预期。
3. host network、host PID、privileged、`/dev` 全量挂载分别有必要性证据；可缩小的权限不得扩大。
4. 两容器 health、自动重启、机器重启后启动和失败回滚通过。
5. 配置只使用占位示例；API key 仅注入 client collector。

## B6 真实数据集成

### 合同

| 项 | 内容 |
| --- | --- |
| 允许修改 | 集成测试/脚本、脱敏报告、Dashboard 数据适配与测试中关闭 fixture-only 路径所需的最小文件；不重做已确认样式 |
| 禁止修改 | 新数据源、字段语义、采集频率、Runs/聊天/审批、secret 输入 UI、无关 UI 重构 |
| 输入 | B2 stats pipeline、B3 host data、B4 Hermes snapshots、B5 Compose、已确认 Dashboard 壳层 |
| 输出 | 1.0/2.0 双跑报告、真实 `/json/stats.json` -> Web 证据、normal/empty/degraded/long 集成测试、fixture-only 模式关闭 |
| 依赖 | B2、B3、B4、B5 与独立 Dashboard 壳层 PR |
| HS | HS-004 至 HS-011、HS-021 至 HS-023 |
| 回滚 | 入口切回 1.0；2.0 Compose 独立停止；保留脱敏对比证据，不迁移/覆盖 1.0 状态 |

### 验收标准

1. 1.0/2.0 至少 24 小时双跑，基础资源、SMART、Docker、Profile 的允许误差与 freshness 有记录。
2. OS/CPU/Hardware/Docker/Hermes 从 source 到 Browser 每一步均有字段一致性证据。
3. CPU 型号单行自适应、三档资源颜色、硬盘约天数、Docker 不折叠及长值布局与已确认预览一致。
4. empty/degraded/long-values 使用真实 Go HTTP stats 形状，不再用 extension-root fake host 证明管线。
5. Browser network/DOM/console/localStorage、server/client logs、stats/OpenAPI 均通过 secret scan。
6. 机器重启、collector/exporter 重启、API unauthorized/timeout、Docker/SMART 权限失败均显示正确 stale/error，不伪装正常。

## 共同测试矩阵

| 层 | Normal | Empty | Degraded | Long values | Security | Restart |
| --- | --- | --- | --- | --- | --- | --- |
| Go model | 必须 | 必须 | 必须 | 必须 | 必须 | 不适用 |
| TCP/NodeState/Snapshot | 必须 | 必须 | 单域隔离 | 必须 | 必须 | 必须 |
| Host collector | 必须 | 必须 | source/permission/parser | 必须 | 必须 | collector restart |
| Hermes exporter | 必须 | 0 Profile | API/CLI/file failure | many/long Profile | 必须 | exporter restart |
| HTTP/OpenAPI | 必须 | 必须 | 必须 | 必须 | 必须 | 必须 |
| Dashboard | 必须 | 必须 | 必须 | 必须 | 必须 | fetch recovery |
| Compose/host | 实机 | 实机 | 注入失败 | 实机抽样 | secret scan | machine reboot |

每个 PR 必须在描述中列出：允许/禁止文件、输入、输出、HS、依赖、执行的命令、未运行项、验收结果和回滚方式。不能用后续 PR 的存在掩盖当前 PR 未达到退出标准。

## 顺序与回滚

1. B1/B2 建立 server 可承载但不要求真实 collector 的管线。
2. B3 与 B4 分开迁移 host 与 Hermes 数据，避免 SMART/Docker 问题阻断 Profile，反之亦然。
3. B5 只在 collector 需求被测试证明后增加 host access。
4. 已确认 Dashboard 壳层保持独立 PR；B6 只完成真实数据接入和集成证据。
5. 每个实现分支从最新 `2.0` 创建 Draft PR，禁止直接推送或自动合并 `2.0`。
6. legacy parser 的移除必须是独立后续 PR，并有旧 client 使用量证据。

## 明确不包含

- Runs、聊天、流式聊天、停止、审批。
- `/api/hermes/config-summary` 服务端管理路由。
- 新 Hermes endpoint 或超过 1.0 的功能。
- Python collector Go 化。
- 删除 C++ 1.0、Nginx、旧脚本或历史兼容代码。
- 覆盖整套 2.0 WebUI、重做已确认 Dashboard 样式。
- 把 Hermes collector 配置写入 ServerStatus node config schema。

## 未决问题

1. DSD-003/004/005/006 的 Proposed 项仍需实机证据与用户确认。
2. 已部署 Dashboard 的未提交文件应先整理为哪个独立 UI PR，不能与 B0 或 B1 至 B5 混合。
3. 本机缺系统 Go toolchain；B1/B2 开始前需固定 CI 或开发容器验证命令。
4. legacy 输入兼容保留一个发布周期还是按时间窗保留。
5. Release A 是否只交付 Profile 外形，B4 的 P1 jobs/sessions/token/config summary/MoA 是否延期到 Release B。
6. 24 小时双跑的允许误差、采样间隔和报告格式。

## 关联文档

- 数据源：[DATA_SOURCE_MAP.md](DATA_SOURCE_MAP.md)
- 调用链：[SOURCE_TRACE.md](SOURCE_TRACE.md)
- 缺口：[DATA_GAP_REPORT.md](DATA_GAP_REPORT.md)
- 决策：[DATA_SOURCE_DECISIONS.md](DATA_SOURCE_DECISIONS.md)
- Go 文件映射：[GO_IMPLEMENTATION_MAP.md](GO_IMPLEMENTATION_MAP.md)
