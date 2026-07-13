# HermesStatus UI 差异

## 目录

- [比较范围](#比较范围)
- [页面与导航](#页面与导航)
- [Dashboard 组件差异](#dashboard-组件差异)
- [JavaScript 差异](#javascript-差异)
- [CSS 与响应式差异](#css-与响应式差异)
- [图标与资源](#图标与资源)
- [删除或隐藏的原生界面](#删除或隐藏的原生界面)
- [迁移建议](#迁移建议)
- [关联文档](#关联文档)

## 比较范围

1.0 的 `web/` 已从 ServerStatus 多节点控制台改写为单主机 HermesStatus 面板；2.0 分支当前仍是 Go ServerStatus 原生多节点 WebUI。本文件描述 1.0 用户可见结果及其迁移价值。

## 页面与导航

| 项目 | 1.0 HermesStatus | 2.0 原生 Go UI | 截图位置描述 | 文件路径 | 建议迁移 |
| --- | --- | --- | --- | --- | --- |
| 页面标题 | 保留“云监控” | “云监控”多节点控制台 | 浏览器标题和左上角品牌 | `web/index.html` | 是，HS-001 |
| 顶部标签 | 只显示“主机” | 主机/监测/SSL/配置等原生标签 | 顶部品牌右侧 | `web/index.html` | 是；单机场景保持简化 |
| 刷新信息 | 显示“上次刷新”及手动刷新按钮 | 秒级原生状态时间 | 顶栏右侧 | `web/index.html`, `web/js/app.js` | 是，HS-011 |
| 新页面 | 无独立新 URL；全部位于主机页 | 多面板单页 | 主内容区 | 同上 | 是 |
| 配置页 | HTML 入口已移除 | 完整 CRUD 配置页 | 当前 1.0 无截图位置 | `web/js/app.js` 有残留函数 | 不迁移残留；见 [LEGACY.md](LEGACY.md) |

## Dashboard 组件差异

| 类型 | 变更 | 内容 | 截图位置描述 | 文件路径 | 建议迁移 |
| --- | --- | --- | --- | --- | --- |
| 修改布局 | 五列概览 | CPU、内存、硬盘、运行中/总容器、已运行时间 | 主机页第一行 | `web/js/app.js`, `web/css/app.css` | 是，HS-002 |
| 修改卡片 | CPU | 百分比条内显示占用；下方显示清洗后的 CPU 型号 | 第一行第 1 张 | 同上 | 是，HS-003/HS-004 |
| 修改卡片 | 内存 | 百分比条；下方显示已用/总量，容量格式取整 | 第一行第 2 张 | 同上 | 是，HS-003 |
| 修改卡片 | 硬盘 | 百分比条；下方显示已用/总量 | 第一行第 3 张 | 同上 | 是，HS-003 |
| 新增卡片 | 容器数量 | `running / total`，无说明文字 | 第一行第 4 张 | 同上 | 是，HS-009 |
| 修改卡片 | 运行时间 | 运行时间主值，下方显示宿主机系统版本，不显示 IP | 第一行第 5 张 | 同上 | 是，HS-004 |
| 新增一行 | 硬件健康 | CPU 温度、硬盘当前/最高/最低温度、SMART、通电时间、写入/读取量 | 概览下方第二行 | `web/js/app.js`, `web/css/app.css` | 是，HS-005 至 HS-008 |
| 新增表格 | Hermes Profiles | 中文列：配置、服务、网关、API、运行模式、模型/模式/提供商、任务、会话、Token | 页面中部第一张数据表 | `web/index.html`, `web/js/app.js` | 是，HS-010 至 HS-017 |
| 新增元信息 | Agent 版本 | 对 Profile 版本去重后展示 | Hermes 标题右侧 | 同上 | 是，HS-017 |
| 新增交互 | Profile 详情 | 点击整行打开宽弹窗 | Hermes 表行 | `web/js/app.js`, `web/css/app.css` | 是，HS-018 至 HS-020 |
| 新增表格 | 辅助模型 | 名称、有效模型、Base URL、超时、并发、语言、extra_body、密钥 configured | Profile 弹窗主体 | 同上 | 是，HS-018 |
| 新增表格 | 容器挂载点 | 宿主机路径、容器路径、模式 | Profile 弹窗辅助模型下方 | 同上 | 是，HS-019 |
| 新增表格 | Mixture of Agents | API 来源、工具集、启用/配置、工具、说明 | Profile 弹窗底部 | 同上 | P2，HS-020 |
| 新增表格 | Docker Containers | ID、名称、状态、创建时间、镜像、命令、端口；不折叠 | 页面下部第二张数据表 | `web/index.html`, `web/js/app.js` | 是，HS-009 |

## JavaScript 差异

| 模块 | 主要函数/行为 | 迁移判断 |
| --- | --- | --- |
| 数据入口 | `fetchData()` 每 10 分钟读取 `json/stats.json`，手动刷新使用 no-store | 保留刷新语义；Go 2.0 可继续使用同 URL |
| 单主机选择 | `firstHost()` 固定取 `servers[0]` | 保留单机场景，但应对空节点和多节点配置给出明确策略 |
| 资源格式化 | `humanBytes*`, `pct`, `usageBand`, `cpuModelText` | 保留显示规则；补单元或浏览器测试 |
| 硬件渲染 | `renderHardware()` | 保留；未知值必须显示 `-` 而不是伪造正常状态 |
| Hermes 表 | `renderHermes()` | 保留；建议拆分纯格式化函数与 DOM 渲染 |
| Docker 表 | `renderDocker()` | 保留不折叠行为；维持横向滚动 |
| Profile 弹窗 | `openProfileModal()`, `auxTable()`, `volumeRows()`, `mixtureOfAgentsTable()` | 保留；仅消费脱敏数据 |
| 管理操作 | `adminToken()`, `postAdmin()`, `bindAdminActions()` | 当前 HTML 没有目标元素，属于不可达遗留 |
| 未使用函数 | `tokenTotalText()` | 当前表只调用 `tokenBreakdownText()`，可不迁移 |

## CSS 与响应式差异

| 差异 | 当前实现 | 文件路径 | 建议迁移 |
| --- | --- | --- | --- |
| 五列网格 | 桌面端稳定五列，窄屏降为单列 | `web/css/app.css` | 是 |
| 占用颜色 | `usage-low`, `usage-medium`, `usage-high` | 同上 | 是 |
| 百分比条 | 条内左对齐文字，CPU/内存/硬盘一致 | 同上 | 是 |
| 数据表 | 最小宽度和 `.table-wrap` 横向滚动 | 同上 | 是 |
| 长文本 | `.wrap-cell`、ellipsis、title tooltip | 同上 | 是 |
| Profile 弹窗 | `width:min(var(--content-max),100%)`，与主页面内容宽度一致 | 同上 | 是 |
| 移动端 | 720px 以下顶栏换行、卡片单列、表格滚动、弹窗缩边距 | 同上 | 是 |
| 卡片视觉 | 深色面板、轻微渐变、边框、8px 左右圆角体系 | 同上 | 迁移时与 2.0 设计变量合并，不整页覆盖 |

## 图标与资源

| 项目 | 状态 | 文件路径 | 建议 |
| --- | --- | --- | --- |
| 品牌心电线图 | 内联 SVG，沿用“云监控”识别 | `web/index.html` | 保留；不是 Hermes 新图标 |
| favicon | 沿用仓库 SVG | `web/favicon.svg` | 原生资产，无需专项迁移 |
| 状态图标 | 无新增图片库；使用文本徽标 | `web/js/app.js`, `web/css/app.css` | 保持无额外依赖 |
| Profile 弹窗关闭 | 文本 `×` | `web/index.html` | 可在 2.0 设计系统内统一，但非功能阻断 |

## 删除或隐藏的原生界面

| 原生功能 | 1.0 状态 | 是否应随 HermesStatus 迁移 |
| --- | --- | --- |
| 多节点主机列表、搜索、过滤、排序、详情 | 被单主机概览替代 | 不迁移到 Hermes 单主机首页；Go 原生能力可留在代码底座 |
| 三网延迟/流量面板 | 页面移除 | 否，除非另立需求 |
| 服务监测 | 页面移除 | 否 |
| SSL 证书 | 页面移除 | 否 |
| Watchdog UI | 页面移除 | 否 |
| 完整配置 CRUD | 页面移除；JS/API 遗留 | 不迁移 Hermes 旧残留；2.0 原生配置能力独立保留 |
| 仅“重载配置/重启服务”配置页 | README 声称存在，但当前 HTML 无配置标签和按钮 | 先澄清产品需求，不能按现状认定为已实现 |

## 迁移建议

1. 不直接用 1.0 三个 Web 文件覆盖 2.0；应在 2.0 现有 CSS 变量、错误处理和 API 生命周期上移植 HS-001 至 HS-025 的可见组件。
2. 第一批用固定 JSON fixture 覆盖正常、unknown、空数组、超长文本、移动端和三档百分比颜色。
3. 所有 Profile 详情仅消费 Go stats 中的脱敏结构，不在浏览器发起 Hermes API 请求。
4. 上次刷新时间应使用 Hermes 数据域自己的采集时间，而不只是 Go stats 每秒写入时间，避免把陈旧 Hermes 数据显示成刚刷新。

## 关联文档

- 功能矩阵：[FEATURE_MATRIX.md](FEATURE_MATRIX.md)
- 数据结构：[API_DIFF.md](API_DIFF.md)、[CONFIG_DIFF.md](CONFIG_DIFF.md)
- 遗留项：[LEGACY.md](LEGACY.md)
- 迁移阶段：[MIGRATION_PLAN.md](MIGRATION_PLAN.md)
