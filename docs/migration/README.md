# HermesStatus 2.0 迁移资产

## 目录

- [目的](#目的)
- [基线](#基线)
- [推荐阅读顺序](#推荐阅读顺序)
- [文档索引](#文档索引)
- [编号与术语](#编号与术语)
- [使用方式](#使用方式)
- [合同校验](#合同校验)
- [B0 数据源审计](#b0-数据源审计)
- [本次范围](#本次范围)

## 目的

本目录用于把 HermesStatus `1.0` 在旧 C++ ServerStatus 上的稳定定制，整理成可迁移到 `2.0` Go ServerStatus 的架构资产。它描述事实、差异、风险和顺序，不包含 Go 功能实现。

## 基线

| 基线 | 含义 |
| --- | --- |
| `1.0` | HermesStatus 当前稳定运行版本：C++ server + Python 管理 API + Nginx + Python client/exporter |
| `2.0` | 同步 cppla/ServerStatus 最新 Go master 的迁移目标基线，当前尚未包含 HermesStatus 定制 |
| 功能编号 | `HS-001` 至 `HS-026`，由 [FEATURE_MATRIX.md](FEATURE_MATRIX.md) 统一定义 |

## 推荐阅读顺序

1. [FEATURE_MATRIX.md](FEATURE_MATRIX.md)：先确认需要迁移的完整功能和优先级。
2. [ARCHITECTURE.md](ARCHITECTURE.md)：理解 1.0 数据流、原生/定制边界和 2.0 缺口。
3. [API_DIFF.md](API_DIFF.md) 与 [CONFIG_DIFF.md](CONFIG_DIFF.md)：确定协议、字段、API 和 secret 边界。
4. [BACKEND_DIFF.md](BACKEND_DIFF.md) 与 [UI_DIFF.md](UI_DIFF.md)：按实现层查找源文件和目标落点。
5. [DEPENDENCY.md](DEPENDENCY.md) 与 [LEGACY.md](LEGACY.md)：避免带入 C++ 依赖和不可达代码。
6. [SCOPE_DECISIONS.md](SCOPE_DECISIONS.md)、[STATS_CONTRACT.md](STATS_CONTRACT.md) 与 [GO_IMPLEMENTATION_MAP.md](GO_IMPLEMENTATION_MAP.md)：确认 Release A 合同和 Go 落点。
7. [DATA_SOURCE_MAP.md](DATA_SOURCE_MAP.md) 与 [SOURCE_TRACE.md](SOURCE_TRACE.md)：核对每个字段的真实来源、刷新、fallback 和传输链。
8. [DATA_GAP_REPORT.md](DATA_GAP_REPORT.md) 与 [DATA_SOURCE_DECISIONS.md](DATA_SOURCE_DECISIONS.md)：确认缺口、阻断和来源决策。
9. [MILESTONE_B_PR_PLAN.md](MILESTONE_B_PR_PLAN.md)：按 B1 至 B6 的独立 PR 边界开始实施。
10. [MIGRATION_PLAN.md](MIGRATION_PLAN.md)：查看完整 P0/P1/P2 发布路线。

## 文档索引

| 文档 | 主要回答的问题 |
| --- | --- |
| [FEATURE_MATRIX.md](FEATURE_MATRIX.md) | 1.0 究竟新增了哪些功能，在哪里实现，是否迁移，优先级是什么？ |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 当前 Backend/Frontend/Protocol/API/Docker/Client/Server 如何协作？哪些原生、哪些定制？ |
| [API_DIFF.md](API_DIFF.md) | HTTP、stats JSON、TCP 和外部 API 有哪些新增、删除、修改及兼容性？ |
| [UI_DIFF.md](UI_DIFF.md) | Dashboard 增删了什么卡片、表格、布局、JS、CSS、图标和页面？ |
| [BACKEND_DIFF.md](BACKEND_DIFF.md) | C++、Python、脚本、测试按 Docker/SMART/Hermes 等模块改了什么？ |
| [CONFIG_DIFF.md](CONFIG_DIFF.md) | 新增了哪些配置、环境变量、JSON 字段、挂载和路径？ |
| [DEPENDENCY.md](DEPENDENCY.md) | apt/pip/npm/docker/submodule/Go 依赖哪些保留、哪些删除？ |
| [LEGACY.md](LEGACY.md) | 哪些未使用、重复、历史兼容或建议废弃，但当前不删除？ |
| [MIGRATION_PLAN.md](MIGRATION_PLAN.md) | 如何按 P0/P1/P2 迁移，工作量多大，能否一次完成？ |
| [SCOPE_DECISIONS.md](SCOPE_DECISIONS.md) | Release A 明确包含和排除什么，哪些架构决策不可在实现 PR 中隐式改变？ |
| [STATS_CONTRACT.md](STATS_CONTRACT.md) | hardware、docker、hermes 的字段、限制、freshness、错误与 secret 边界是什么？ |
| [GO_IMPLEMENTATION_MAP.md](GO_IMPLEMENTATION_MAP.md) | 合同如何映射到 Go 文件、类型、验证位置和后续 PR？ |
| [DATA_SOURCE_MAP.md](DATA_SOURCE_MAP.md) | 每个 P0 字段从哪里采集、多久刷新、如何失败、进入哪个输出、如何验证？ |
| [SOURCE_TRACE.md](SOURCE_TRACE.md) | 1.0/2.0 从 source 到 collector、wire、server、stats 和 browser 的链路在哪里断开？ |
| [DATA_GAP_REPORT.md](DATA_GAP_REPORT.md) | 当前缺口、风险、未验证项和 B1/B2/B3 阻断是什么？ |
| [DATA_SOURCE_DECISIONS.md](DATA_SOURCE_DECISIONS.md) | 宿主机身份、SMART、Docker、Hermes、freshness 和 secret 采用什么来源规则？ |
| [MILESTONE_B_PR_PLAN.md](MILESTONE_B_PR_PLAN.md) | 后续 Go model、pipeline、client、Dashboard 和 Compose PR 如何隔离？ |
| [schema/](schema/) | Agent update 与 stats 扩展的 Draft 2020-12 JSON Schema。 |
| [../../testdata/migration](../../testdata/migration) | 正常、空、降级和长值的脱敏合同 fixture。 |

## 编号与术语

- `HS-xxx`：HermesStatus 功能编号，只在 [FEATURE_MATRIX.md](FEATURE_MATRIX.md) 定义，其他文档引用同一含义。
- `ServerStatus 原生`：上游提供的节点采集、TCP、stats、管理 API、SSL 和原生 WebUI；Release C 不保留告警引擎。
- `HermesStatus 自定义`：针对 J4125、SMART、Docker 和 Hermes Agent Profile 新增或改写的能力。
- `等价迁移`：2.0 用户可见行为和数据来源达到 1.0 稳定部署效果，不等同于技术栈全部重写。
- `estimated`：Token 等值来自本地状态/日志兜底，不能当作稳定全局成本账本。

## 使用方式

- 架构评审以功能矩阵为范围清单，以 API/配置文档为合同。
- 实施任务必须引用至少一个 `HS-xxx`，并在完成时补测试和实机证据。
- 发现 1.0 文档与运行代码不一致时，以代码调用关系和已部署结果为准，并在 [LEGACY.md](LEGACY.md) 记录。
- 新需求不得混入“1.0 等价迁移”；例如完整 Runs/聊天/审批操作应单独立项。

## 合同校验

在仓库根目录执行：

```bash
python3 scripts/validate_migration_contracts.py
```

该脚本只使用 Python 标准库，检查 Markdown 内部链接和章节锚点、两份 Schema 的 Draft 声明与示例、八份 fixture 的结构和跨字段语义、payload 上限，以及 fixture 中的明显 secret 和真实私网地址模式。

## B0 数据源审计

B0 在合同之后增加运行事实审计，不实现业务代码：

1. [DATA_SOURCE_MAP.md](DATA_SOURCE_MAP.md) 是逐字段权威索引，包含物理机与 client 容器验证命令。
2. [SOURCE_TRACE.md](SOURCE_TRACE.md) 记录 1.0 双重 SMART 所有权、JSON-in-string 链路及 2.0 的实际丢失点。
3. [DATA_GAP_REPORT.md](DATA_GAP_REPORT.md) 将字段标为正确、来源错误、collector 缺失、wire 丢弃、contract-only 或 UI-only。
4. [DATA_SOURCE_DECISIONS.md](DATA_SOURCE_DECISIONS.md) 区分 Accepted、Proposed、Blocked 与 Deferred 决策。
5. [MILESTONE_B_PR_PLAN.md](MILESTONE_B_PR_PLAN.md) 只规划后续 PR；B0 确认前不得开始 B1/B2/B3 编码。

审计以代码调用关系为事实基线，同时把已由用户确认并部署、但尚未推送的本地 P0 Dashboard 作为 UI 消费端证据。文档 PR 不夹带这些 Web 业务文件。

## 本次范围

第一阶段文档记录 1.0 与 2.0 的迁移差异；第二阶段增加 Release A 范围决策、可执行 stats 合同、JSON Schema、fixture 和 Go 实施映射；B0 再固化真实数据来源、传输断点和实施门。以上文档阶段不修改 Go/Python 业务代码、WebUI、CI、Dockerfile、Compose 或项目根 README，也不实现 Hermes API 调用。
