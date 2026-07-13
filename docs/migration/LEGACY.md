# HermesStatus 遗留与废弃候选

## 目录

- [使用说明](#使用说明)
- [未使用或不可达](#未使用或不可达)
- [重复实现](#重复实现)
- [仅历史兼容](#仅历史兼容)
- [建议废弃但暂不删除](#建议废弃但暂不删除)
- [迁移约束](#迁移约束)
- [关联文档](#关联文档)

## 使用说明

本文件只记录，不删除任何代码。条目基于 1.0 当前调用关系和 2.0 Go 基线，迁移前仍应通过运行数据、访问日志或调用方确认。

## 未使用或不可达

| 条目 | 文件/位置 | 现状证据 | 建议 |
| --- | --- | --- | --- |
| 配置管理前端函数 | `web/js/app.js`: `setAdminStatus`, `adminToken`, `postAdmin`, `bindAdminActions` | 当前 `web/index.html` 没有 config panel、`adminReload`、`adminRestart` 或 `adminStatus` 元素 | 不迁移这组 1.0 残留；若需要管理功能，使用 2.0 原生配置页重新定义 |
| `tokenTotalText()` | `web/js/app.js` | 当前只调用 `tokenBreakdownText()` | 不迁移 |
| `switchTab()` 的多标签能力 | `web/js/app.js` | HTML 只有 `data-tab="host"` | 可简化，不作为功能迁移 |
| exporter `runs` | `scripts/export-hermes-status.py` | Profile payload 固定 `"runs": []`，没有 Runs API 调用 | 不宣称为现有功能；新增 Runs 需独立设计 |
| exporter 明细 | 同上 `jobs`, `sessions`, `capabilities` | `client-psutil.py` 读取 Profile JSON 时不将这些字段放入最终 `hermes_json` | 不迁移未消费明细，除非 UI/API 有明确需求 |
| `running_agents`, `resource_status` | exporter/client | 仍采集和上报，但当前 Hermes 表已删除显示 | 评估删除，避免扩大 schema |
| `note`, `last_run_at`, `yesterday_*` | exporter/client | 最终 UI 不显示；仅作为回退/诊断数据 | 只保留必要诊断字段，明确统计窗口 |
| `/api/hermes/config-summary` | `server/manage_api.py` | 当前 WebUI 直接读取 stats 中 `config_summary`，无前端调用 | 查外部调用者；无调用则不迁移或改为通用只读 stats API |

## 重复实现

| 条目 | 文件 | 风险 | 建议 |
| --- | --- | --- | --- |
| SMART 解析 | `clients/client-psutil.py`, `scripts/export-hermes-status.py` | 两份 Device Statistics、健康、温度、LBA 换算逻辑易漂移 | 迁移后只保留一个采集所有者；首阶段指定 exporter 或 client 为权威 |
| Hardware JSON 合并 | exporter 写 `hardware.json`，client 又实时采集并合并 | freshness 和 unknown 覆盖规则复杂 | 为字段增加 source/updated_at，定义单向兜底 |
| API/CLI/本地日志多重回退 | `profile_stats()` | 同一字段来源不透明，可能把不同统计窗口混合 | 输出 `source` 和 `window`，不要只给数字 |
| Profile 路径配置 | JSON、环境变量、Profile `.env`、候选路径 | 优先级多且难排障 | 保留显式注册表为第一优先，兼容路径逐步废弃 |

## 仅历史兼容

| 条目 | 说明 | Go 迁移建议 |
| --- | --- | --- |
| `client-linux.py` 三个空 JSON 字段 | 为非 psutil client 维持协议形状，但没有业务数据 | Go 字段设为 optional，无需发送空 JSON 字符串 |
| `<PROFILE>_API_SERVER_KEY` 等多种 Token 名称 | 兼容既有部署 | 保留一个过渡版本并记录弃用告警 |
| 默认端口表 hermes1/2/3 | 注册表缺失时的旧默认 | 使用配置驱动；不再作为新部署主路径 |
| 简化 YAML parser | 没有 PyYAML 时的兜底 | 生产镜像已安装 PyYAML；可保留只读失败兜底，不保证完整语义 |
| C++ 64 KiB 包和固定 char buffer | 旧 server 实现约束 | Go 使用结构化类型和独立限额，不复制 |
| C++ stats 手工逗号修复/堆分配 | 解决旧实现的序列化和栈空间问题 | Go 标准 JSON 后无需迁移 |
| `SERVERSTATUS_USER` + `USER` 双写 | 规避 Compose 宿主机 `$USER` | 2.0 可统一使用明确变量并保持一次兼容映射 |
| `SERVER_PYTHON_IMAGE`, `SERVER_DEBIAN_IMAGE` | C++ server 构建可替换镜像 | Go server 不需要 |

## 建议废弃但暂不删除

| 条目 | 原因 | 前置确认 |
| --- | --- | --- |
| `server/manage_api.py`、Nginx、C++ server | 2.0 Go 单进程已完整取代原生职责 | Go Hermes 字段、API、静态 UI 完成并通过回归 |
| `plugin/` Telegram | 2.0 已删除且 HermesStatus 功能不依赖 | 确认生产未单独运行 plugin compose |
| `service/status-server.service` 的 C++ `sergate` 启动方式 | 与推荐 Compose 和 Go 2.0 不一致 | 新 systemd/Compose 启动验证 |
| `status.sh` 旧 C++ 安装路径 | 1.0 与当前容器部署模式不一致 | 2.0 脚本成为唯一非容器安装入口 |
| Profile 本地 logs 扫描 | P2 fallback，统计语义不稳定且可能重 | Hermes API usage 稳定并能覆盖需要的统计窗口 |
| 浏览器 localStorage 中旧 admin token 键 | 当前页面无管理入口 | 前端残留代码移除或接入 2.0 原生配置页 |
| `privileged:true` | 权限过宽 | 验证 `devices:` 与最小 capability 能稳定执行 smartctl |
| host PID + `nsenter` | 扩大容器权限 | 提供稳定的 Hermes CLI/API 宿主机代理后移除 |

## 迁移约束

1. 遗留条目不能在首批迁移中顺手删除；先建立等价测试，再单独清理。
2. README 中“配置页只保留重载和重启”与当前 HTML 不一致，迁移前需要产品决策，不能以文档描述替代运行事实。
3. Runs、完整 Jobs/Sessions 管理、聊天/stream、stop/approval 并非 1.0 已交付界面，不能计入等价迁移完成标准。
4. Token 数值只有在 source/window 明确时才能用于历史趋势或成本判断。

## 关联文档

- 功能现状：[FEATURE_MATRIX.md](FEATURE_MATRIX.md)
- API 事实：[API_DIFF.md](API_DIFF.md)
- 文件差异：[BACKEND_DIFF.md](BACKEND_DIFF.md)
- 迁移计划：[MIGRATION_PLAN.md](MIGRATION_PLAN.md)
