# HermesStatus 2.0 迁移计划

## 目录

- [目标与原则](#目标与原则)
- [工作量定义](#工作量定义)
- [前置基线](#前置基线)
- [P0 核心迁移](#p0-核心迁移)
- [P1 Hermes 与完整体验](#p1-hermes-与完整体验)
- [P2 优化与扩展](#p2-优化与扩展)
- [发布与回滚](#发布与回滚)
- [是否建议一次迁移](#是否建议一次迁移)
- [完成标准](#完成标准)
- [关联文档](#关联文档)

## 目标与原则

目标是在 2.0 Go ServerStatus 上恢复 1.0 已稳定运行的 HermesStatus 行为，同时保留 Go 2.0 的单进程服务、强类型模型、管理 API、OpenAPI 和原生测试体系。

原则：

- 先等价迁移，再清理或重写。
- 第一阶段复用 Python 采集器，Go 端负责协议、验证、状态和 HTTP 输出。
- API Key 只停留在客户端采集容器。
- 每个数据域有 source、updated_at 和 stale/error 状态。
- 原生 ServerStatus 能力与 Hermes 单主机 UI 解耦，避免再次形成难以上游同步的整页覆盖。

## 工作量定义

| 级别 | 参考工作量 | 说明 |
| --- | --- | --- |
| XS | <= 0.5 人日 | 文案、配置映射、简单 schema |
| S | 1-2 人日 | 单一组件或小型采集适配，含测试 |
| M | 3-5 人日 | 跨 client/server/web 的完整功能 |
| L | 1-2 周 | 多数据源、错误处理、部署和端到端验证 |
| XL | >2 周 | 大范围重写或高不确定性功能 |

## 前置基线

| 工作项 | 关联功能 | 工作量 | 一次迁移建议 | 产物 |
| --- | --- | --- | --- | --- |
| 固化 1.0 实机 JSON fixture 和页面截图 | 全部 | S | 单独先做 | 正常/异常/空数据 fixtures、桌面/移动截图 |
| 建立 1.0 与 2.0 字段合同 | HS-004 至 HS-022 | S | 单独先做 | JSON Schema/OpenAPI 草案、source/window 定义 |
| 明确配置页、summary API、Runs 是否在 2.0 范围 | HS-024 及遗留项 | XS | 单独决策 | ADR/范围确认 |
| 建立双栈部署和回滚目录 | 全部 | S | 单独先做 | 1.0/2.0 独立端口与数据目录 |

## P0 核心迁移

| 顺序 | 工作项 | 关联功能 | 工作量 | 是否建议一次迁移 | 验证重点 |
| --- | --- | --- | --- | --- | --- |
| 1 | Go `AgentStats` 增加 Hardware/Docker/Hermes 类型、字段验证和域级限额 | HS-022 | M | 与第 2 项一起 | 未知字段、超长字段、超大数组、旧客户端兼容 |
| 2 | TCP update 与 `SnapshotStats()` 贯通扩展结构 | HS-022 | M | 与第 1 项一起 | 客户端上报后 stats 不丢字段；持久化/恢复行为 |
| 3 | 移植 Python 宿主机身份、SMART、温度、Docker 采集器 | HS-004 至 HS-009 | L | 分模块提交，同一 P0 发布 | smartctl JSON/文本、设备缺失、Docker Socket 失败、容器长命令 |
| 4 | 移植注册表、周期 exporter、原子快照和配置挂载 | HS-010, HS-011, HS-023 | M | 可与第 3 项并行 | 自定义 Profile 名称/路径、600 秒刷新、重启恢复 |
| 5 | 落实 Token/secret 安全边界 | HS-021 | M | 必须在任何 Hermes API 上线前完成 | stats、日志、错误、OpenAPI、浏览器均无 secret |
| 6 | 移植单主机概览、三档资源条和硬件/Docker 表 | HS-001 至 HS-009 | L | 后端合同稳定后一次发布 | 三色阈值、空数据、移动端、容器不折叠 |
| 7 | Compose 迁移到 Go server，保留两容器和必要宿主机挂载 | HS-023, HS-026 | M | 与 P0 发布一起 | 重启自启动、health、端口、权限最小化基线 |

P0 完成后应得到：Go server + Python client/exporter 的可运行单主机面板，硬件和 Docker 与 1.0 实机数据一致，Hermes 密钥边界已就绪。

## P1 Hermes 与完整体验

| 顺序 | 工作项 | 关联功能 | 工作量 | 是否建议一次迁移 | 验证重点 |
| --- | --- | --- | --- | --- | --- |
| 1 | Hermes loopback API client、health/detailed health | HS-012 | M | 与安全测试一起 | 200/401/timeout/invalid JSON、各 Profile 隔离 |
| 2 | CLI status/版本解析与宿主机执行策略 | HS-013, HS-014, HS-017 | M | 可独立 | 两种 CLI profile 参数、ANSI、缺段落、Provider/Auth/API 模式 |
| 3 | Jobs/Sessions 分页与统计 | HS-015 | M | 独立 | has_more、声明 total、0 jobs、CLI fallback |
| 4 | Token usage 统计合同 | HS-016 | L | 不与 UI 同时猜测 | input/output/total、estimated、source、统计窗口、重复计数 |
| 5 | Profile 配置摘要、辅助模型继承和脱敏 | HS-018, HS-021 | M | 与弹窗一起 | 显式模型、auto 继承、secret、损坏 YAML、路径优先级 |
| 6 | docker_volumes 展示 | HS-019 | S | 与第 5 项一起 | `host:target:ro`、无 mode、路径缺失 |
| 7 | Hermes 中文表格、版本和宽详情弹窗 | HS-012 至 HS-019、HS-025 | L | 后端字段稳定后一次发布 | 表头、状态 badge、长模型名、宽表、移动端 |
| 8 | 领域刷新时间与陈旧状态 | HS-011, HS-014 | S | 与 Hermes UI 一起 | stats 每秒更新不能掩盖 10 分钟旧 Hermes 数据 |

P1 完成后达到 1.0 主要用户体验等价。Token 功能必须以明确的统计语义验收，而不是只检查非零数字。

## P2 优化与扩展

| 工作项 | 关联功能 | 工作量 | 是否建议一次迁移 | 建议 |
| --- | --- | --- | --- | --- |
| Mixture of Agents toolset | HS-020 | S | 可独立 | `/v1/toolsets` 稳定后迁移 |
| Hermes 配置摘要管理 API/OpenAPI | HS-024 | S | 可独立 | 有外部调用者才保留 |
| 构建镜像/WEB_PORT/账号兼容整理 | HS-026 | S | 可独立 | 保留有用参数，删除 C++ build args |
| SMART 重复实现合并 | HS-005 至 HS-008 | M | 等价后独立 | 先确定唯一采集所有者 |
| 去除 privileged/host PID | HS-023 | L | 独立安全项目 | 通过 devices/capability 或宿主机代理替代 |
| Python 采集器 Go 化评估 | HS-004 至 HS-020 | XL | 不建议与等价迁移合并 | 仅在维护收益明确时启动 |
| Runs/完整 Jobs/Sessions 操作 | 非现有 HS 功能 | XL | 全新项目 | 重新做权限、审批、停止和流式交互设计 |

## 发布与回滚

1. 1.0 保持当前目录、镜像标签、端口和数据目录不变。
2. 2.0 使用独立 Compose project、Web 端口和 stats/status 目录，先只读同一宿主机数据。
3. 使用固定 fixture 做自动回归，再做至少 24 小时双跑对比：CPU/内存/磁盘、SMART、容器数、三 Profile 状态、会话/任务、Token 和更新时间。
4. 切换前导出 1.0 `stats.json`、`hermes-status/`、有效 Compose 配置和页面截图。
5. 回滚只切换入口端口/反代到 1.0，不让 2.0 修改 Hermes Profile 配置或 API Key。

## 是否建议一次迁移

**不建议。** 推荐三次可验证发布：

| 发布 | 范围 | 原因 |
| --- | --- | --- |
| Release A | P0 协议、硬件、SMART、Docker、单主机基础 UI | 先证明 Go 数据通路与宿主机采集稳定 |
| Release B | P1 Hermes health/CLI/jobs/sessions/token/config summary/UI | 隔离 Hermes API 与统计语义风险 |
| Release C | P2 MoA、运维 API、权限收敛、遗留清理 | 不阻塞主要业务等价 |

任何 Release 都不应同时重写 Python 采集器为 Go；等价行为稳定后再做技术栈收敛。

## 完成标准

- [ ] [FEATURE_MATRIX.md](FEATURE_MATRIX.md) 中所有 P0/P1 行有 Go 2.0 实现、自动测试和实机证据。
- [ ] 1.0 和 2.0 同一时刻的关键数据在允许误差内一致。
- [ ] API Key 未出现在 stats、HTTP 响应、前端存储、日志和截图。
- [ ] SMART 的 passed、温度三值、通电小时、写入/读取量与 `smartctl -x` 一致。
- [ ] Docker running/total 和列表与 `docker ps -a` 一致。
- [ ] 每 Profile 的 health、CLI model/provider/mode/refresh、jobs、sessions 和 Token 来源可追踪。
- [ ] 桌面与移动端无溢出、重叠或折叠容器列表。
- [ ] 服务重启、自启动、配置缺失、API 401、Docker/SMART 不可用均有降级结果。
- [ ] 1.0 回滚路径经过演练。

## 关联文档

- 总功能：[FEATURE_MATRIX.md](FEATURE_MATRIX.md)
- 架构：[ARCHITECTURE.md](ARCHITECTURE.md)
- API：[API_DIFF.md](API_DIFF.md)
- UI：[UI_DIFF.md](UI_DIFF.md)
- 后端：[BACKEND_DIFF.md](BACKEND_DIFF.md)
- 遗留：[LEGACY.md](LEGACY.md)
