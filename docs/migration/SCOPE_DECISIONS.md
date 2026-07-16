# HermesStatus 2.0 范围决策

## 目录

- [目的](#目的)
- [Release A 范围](#release-a-范围)
- [已确认决策](#已确认决策)
- [明确不在范围内](#明确不在范围内)
- [架构约束](#架构约束)
- [验收边界](#验收边界)
- [关联文档](#关联文档)

## 目的

本文固化 HermesStatus 2.0 Release A 的范围，防止等价迁移被上游能力、P1/P2 Hermes 功能或技术栈重写扩大。若后续需要改变这些决策，应单独提交 ADR 或范围变更，不得在实现 PR 中隐式修改。

## Release A 范围

Release A 只覆盖以下既有功能：

- HS-004 至 HS-011：宿主机身份、温度、SMART、硬盘寿命与累计 I/O、Docker 清单、多 Profile 注册、周期快照。
- HS-021：凭证和脱敏边界。
- HS-022：扩展上报协议、结构化模型和限额。
- HS-023：客户端容器访问宿主机数据源所需的部署边界。

本阶段交付物是合同、Schema、fixture 和 Go 实施映射，不实现上述业务功能。

## 已确认决策

| 决策 | 结论 | 理由 | 后续影响 |
| --- | --- | --- | --- |
| 首页形态 | HermesStatus 2.0 首页继续采用单主机 Dashboard | 1.0 已运行场景固定为单台 J4125，核心工作流是本机硬件、Docker 和 Hermes 状态 | P0 Dashboard 在 2.0 组件体系内实现，不恢复 1.0 多节点首页 |
| 上游 Go 能力 | 保留 Go 上游原生管理 API、OpenAPI、SSL 状态检查和配置能力 | Release C 明确不包含告警引擎 | UI 继续只展示单主机状态，后端不提供告警 CRUD 或通知回调 |
| Hermes summary API | Release A 不迁移 `/api/hermes/config-summary` | 当前 1.0 WebUI 不调用；属于 HS-024/P2 | 不在 `server/http_server.go` 增加该路由 |
| 未交付能力 | Runs、聊天、流式聊天、停止、审批等不计入 1.0 等价迁移 | 1.0 exporter 的 `runs` 恒为空，页面没有这些交互 | 需要时作为独立产品需求和安全设计 |
| 采集器策略 | 第一阶段继续复用 Python client/exporter | 先隔离 Go 数据管线风险，避免同时重写采集器 | Go 仅接收、验证、存储和输出结构化数据 |
| API Key 所在位置 | Hermes API Key 仅存在客户端采集侧 | 浏览器和服务端无需调用 Hermes API | Key 不进入 TCP payload、stats、日志、OpenAPI 示例或浏览器 |
| Web 迁移方式 | 不直接使用 1.0 Web 文件覆盖 2.0 WebUI | 全量覆盖会丢失上游管理、错误处理和后续同步能力 | 在 2.0 的现有组件和样式变量上增量实现 Dashboard |
| ServerStatus 配置 | 不把 HermesStatus 扩展字段加入 `server/config.json` 节点配置 schema | 扩展是采集结果和独立 collector 配置，不是 ServerStatus 节点身份配置 | Profile/path/API 配置继续独立维护 |

## 明确不在范围内

| 不在 Release A 的内容 | 关联说明 |
| --- | --- |
| HS-012 至 HS-020 的 Hermes API/CLI、Jobs、Sessions、Token 统计、辅助模型、挂载 UI、MoA | Schema 仅为稳定外形预留必要字段；不实现数据采集或界面 |
| HS-024 `/api/hermes/config-summary` | 不新增路由，不加入 OpenAPI operation |
| HS-025 完整 Hermes Profile 详情 UI | Release A 只处理 P0 Dashboard 数据管线 |
| Python 采集器 Go 化 | 属于迁移稳定后的独立 XL 项目 |
| 最小化 `privileged`、host PID 或 `nsenter` | Release A 先保持 1.0 可用边界，后续单独做权限收敛 |
| 清理 1.0 C++、Nginx、Python 管理 API 或历史脚本 | 本 PR 不删除任何遗留代码 |
| CI、Dockerfile、Compose 和 WebUI 变更 | 合同阶段禁止修改，分别留给后续 PR |

## 架构约束

1. 扩展对象只通过客户端 TCP `update` 进入 Go 服务端，不允许浏览器直连 Hermes API。
2. 新结构化字段为 `hardware`、`docker`、`hermes`；旧 `hardware_json`、`docker_json`、`hermes_json` 仅作有期限的输入兼容。
3. 服务端必须对白名单字段、字符串长度、数组数量和数值范围进行验证。
4. 旧 JSON 字符串解析完成后立即丢弃原文，不持久化、不记录日志、不回显。
5. 扩展数据不参与 ServerStatus 原生节点配置 CRUD，也不改变 `server/config.json` schema。
6. 扩展数据错误不能阻断基础 CPU/内存/磁盘/网络 update；服务端应保留基础指标并把扩展域降级为安全 error。
7. Go 服务重启后不把持久化扩展数据恢复为新鲜状态；等待客户端重新上报。

## 验收边界

Release A 合同阶段完成标准：

- [STATS_CONTRACT.md](STATS_CONTRACT.md) 明确定义所有扩展字段、freshness、错误和输出权限。
- 两份 Draft 2020-12 Schema 只描述扩展对象并拒绝未知字段。
- 八份 fixture 覆盖正常、空、降级和边界长值，且全部通过 Schema 校验。
- fixture 不含真实 IP、密码、API Key、Authorization 或原始配置内容。
- [GO_IMPLEMENTATION_MAP.md](GO_IMPLEMENTATION_MAP.md) 将合同映射到五个 Go 文件和后续 PR。

## 关联文档

- 功能范围：[FEATURE_MATRIX.md](FEATURE_MATRIX.md)
- 架构边界：[ARCHITECTURE.md](ARCHITECTURE.md)
- 数据合同：[STATS_CONTRACT.md](STATS_CONTRACT.md)
- 实施映射：[GO_IMPLEMENTATION_MAP.md](GO_IMPLEMENTATION_MAP.md)
- 总计划：[MIGRATION_PLAN.md](MIGRATION_PLAN.md)
