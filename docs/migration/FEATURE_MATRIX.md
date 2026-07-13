# HermesStatus 功能矩阵

## 目录

- [范围与基线](#范围与基线)
- [功能矩阵](#功能矩阵)
- [优先级定义](#优先级定义)
- [关联文档](#关联文档)

## 范围与基线

本表以 `1.0` 分支相对其 C++ ServerStatus 基线的定制为识别范围，以 `2.0` 分支的 Go ServerStatus 为迁移目标。编号 `HS-001` 至 `HS-026` 是本目录内唯一的功能编号体系。

## 功能矩阵

| 编号 | 功能名称 | 功能说明 | 用户可见位置 | 后端实现文件 | 前端实现文件 | API/协议 | 是否修改数据库/配置 | 依赖 | 是否需要迁移 | 优先级 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HS-001 | 单主机信息架构 | 将原多节点、监测、证书和配置导航收敛为 J4125 单主机主页，保留“云监控”标题 | 顶部导航、主机页 | `server/config.json` | `web/index.html`, `web/js/app.js`, `web/css/app.css` | `GET /json/stats.json` | 修改 ServerStatus JSON 配置；无数据库 | 无 | 是 | P0 |
| HS-002 | 五项运行概览 | 展示 CPU、内存、硬盘、运行中/总容器数量、已运行时间 | 主机页第一行 | `clients/client-psutil.py` | `web/js/app.js`, `web/css/app.css` | stats 快照 | 无数据库 | HS-008 | 是 | P0 |
| HS-003 | 统一资源占用条 | CPU/内存/硬盘使用统一百分比条，`<=60%` 绿、`61-80%` 黄、`>80%` 红 | 第一行前三张卡片 | 无 | `web/js/app.js`, `web/css/app.css` | 无 | 否 | HS-002 | 是 | P0 |
| HS-004 | 物理机身份透传 | 读取物理机 CPU 型号和宿主机 `/etc/os-release`，避免显示容器系统信息 | CPU 卡、运行时间卡 | `clients/client-psutil.py`, `docker-compose-client.yml` | `web/js/app.js` | TCP `update`; stats `hardware.cpu_model`, `os` | 新增环境变量和只读挂载 | HS-022 | 是 | P0 |
| HS-005 | CPU 温度 | 从宿主机 hwmon 读取 CPU 温度 | 硬件健康第二行 | `clients/client-psutil.py`, `scripts/export-hermes-status.py` | `web/js/app.js` | stats `hardware.cpu_temperature` | 新增 `/sys/class/hwmon` 挂载 | HS-022 | 是 | P0 |
| HS-006 | SMART 健康状态 | 执行 `smartctl -x`，解析 overall-health `PASSED/FAILED` | 硬件健康第二行 | `clients/client-psutil.py`, `scripts/export-hermes-status.py` | `web/js/app.js` | stats `hardware.disk_smart_status` | 新增 `SMART_DEVICE` 和设备挂载 | HS-022 | 是 | P0 |
| HS-007 | SMART 温度统计 | 从 Device Statistics GP Log 读取当前/最高/最低温度 | 硬件健康第二行 | `clients/client-psutil.py`, `scripts/export-hermes-status.py` | `web/js/app.js` | stats `hardware.disk_temperature` | 同 HS-006 | HS-006 | 是 | P0 |
| HS-008 | 硬盘寿命与累计 I/O | 读取通电小时、逻辑扇区写入/读取并换算字节 | 硬件健康第二行 | `clients/client-psutil.py`, `scripts/export-hermes-status.py` | `web/js/app.js` | stats `disk_power_on_hours`, `disk_written_bytes`, `disk_read_bytes` | 同 HS-006 | HS-006 | 是 | P0 |
| HS-009 | Docker 容器清单 | 通过 Docker Unix Socket 获取运行中/总数及 `docker ps -a` 风格清单 | 概览容器卡、Docker Containers 表 | `clients/client-psutil.py` | `web/index.html`, `web/js/app.js` | Docker `GET /containers/json?all=1`; stats `docker` | 新增 Docker Socket 挂载和限额变量 | HS-021, HS-022 | 是 | P0 |
| HS-010 | 多 Profile 注册表 | Profile 名称、目录、配置、env、API 地址均由 JSON 配置驱动 | Hermes 表每行 | `hermes-exporter.json`, `scripts/export-hermes-status.py` | `web/js/app.js` | 每实例独立 API | 新增 `hermes-exporter.json` | 无 | 是 | P0 |
| HS-011 | 周期导出与快照 | 每 600 秒采集 Hermes/SMART，原子写入 profile 与 hardware JSON；网页显示上次刷新时间 | 顶栏刷新时间 | `clients/entrypoint.sh`, `scripts/export-hermes-status.py` | `web/js/app.js` | 本地 JSON + stats `updated` | 新增状态目录和刷新间隔 | HS-010 | 是 | P0 |
| HS-012 | Hermes 服务健康 | 使用每个 Profile 的 `GET /health` 作为服务状态，并读取 detailed health | Hermes 表服务/API 状态 | `scripts/export-hermes-status.py` | `web/js/app.js` | Hermes `GET /health`, `GET /health/detailed` | API 必须启用并配置 Bearer Token | HS-010, HS-020 | 是 | P1 |
| HS-013 | Gateway 与运行模式 | 解析 `hermes -p <profile> status` 的 Gateway Service 状态和 Manager | Hermes 表网关状态、运行模式 | `scripts/export-hermes-status.py` | `web/js/app.js` | 主机 CLI | 依赖 Hermes 主机目录和命令 | HS-010, HS-022 | 是 | P1 |
| HS-014 | 模型与认证来源 | 解析主模型、Provider、API/Auth 使用模式及已登录 Provider 的刷新时间 | Hermes 表、Profile 详情主模型 | `scripts/export-hermes-status.py` | `web/js/app.js` | 主机 CLI；health 仅作 Provider 兜底 | 否 | HS-013 | 是 | P1 |
| HS-015 | 定时任务与会话统计 | 获取任务启用/总数、会话活动/总数；API 不可用时回退 CLI | Hermes 表定时任务、会话数 | `scripts/export-hermes-status.py` | `web/js/app.js` | Hermes `GET /api/jobs`, `GET /api/sessions` | 分页参数可配置 | HS-012 | 是 | P1 |
| HS-016 | Token 使用量 | 汇总 session/jobs/health 返回的 input/output/total token；本地日志回退标记 `estimated` | Hermes 表 Token 列 | `scripts/export-hermes-status.py`, `clients/client-psutil.py` | `web/js/app.js` | Hermes API usage 字段；本地 JSON 兜底 | 无数据库；快照累计不保证全局账本语义 | HS-012, HS-015 | 是 | P1 |
| HS-017 | Hermes Agent 版本 | 在宿主机执行 `hermes --version` 并去重展示 | Hermes 模块标题右侧 | `scripts/export-hermes-status.py` | `web/index.html`, `web/js/app.js` | 主机 CLI | 否 | HS-022 | 是 | P1 |
| HS-018 | Profile 配置摘要 | 安全解析主模型、Delegation、运行开关和指定辅助模型；`auto`+空模型继承主模型 | 点击 Profile 后的详情弹窗 | `scripts/hermes_config_summary.py`, `scripts/export-hermes-status.py` | `web/js/app.js`, `web/css/app.css` | 嵌入 stats；另有管理 API | 读取 Profile `config.yaml` | HS-010, HS-020 | 是 | P1 |
| HS-019 | 容器挂载点展示 | 读取 `terminal.docker_volumes` 并拆分宿主机路径、容器路径和模式 | Profile 详情弹窗表格 | `scripts/hermes_config_summary.py` | `web/js/app.js` | stats `config_summary.docker_volumes` | 读取 Profile `config.yaml` | HS-018 | 是 | P1 |
| HS-020 | Mixture of Agents 能力 | 在 toolsets 中识别 `moa`/`mixture_of_agents` 并展示可用、启用、配置和工具 | Profile 详情弹窗 | `scripts/export-hermes-status.py` | `web/js/app.js` | Hermes `GET /v1/toolsets` | 否 | HS-012 | 是 | P2 |
| HS-021 | 采集凭证安全 | API Key 仅在采集端读取；强制 Bearer；`0.0.0.0/::` 回写 loopback；摘要只暴露 configured 标记 | 无直接界面；影响所有 Hermes 数据 | `scripts/export-hermes-status.py`, `scripts/hermes_config_summary.py` | 无 | `Authorization: Bearer ...` | 新增敏感环境变量/配置字段，前端不持有密钥 | HS-010 | 是 | P0 |
| HS-022 | 扩展上报协议与限额 | TCP `update` 新增 `hardware_json`、`docker_json`、`hermes_json`，包上限 64 KiB，列表按字节裁剪 | 间接支撑全部定制数据 | `clients/client-linux.py`, `clients/client-psutil.py`, `server/src/main.cpp`, `server/src/main.h`, `server/src/network.h` | TCP 行协议；stats 三个嵌套对象 | 新增 payload 限额环境变量 | HS-005 至 HS-020 | 是 | P0 |
| HS-023 | 容器化宿主机采集权限 | 客户端使用 host network/PID、设备、hwmon、Docker Socket、Hermes 目录和状态目录挂载 | 部署层 | `Dockerfile.client`, `docker-compose-client.yml` | 无 | Docker Compose | 显著修改部署权限和挂载 | HS-004 至 HS-020 | 是 | P0 |
| HS-024 | Hermes 配置摘要 API | 管理端按 Profile 返回 stats 中已脱敏的 `config_summary` | 当前 UI 无入口；供运维/API 使用 | `server/manage_api.py`, `server/entrypoint-server.sh` | 无直接调用 | `GET /api/hermes/config-summary?profile=` | 使用 `ADMIN_TOKEN` | HS-018, HS-021 | 评估后迁移 | P2 |
| HS-025 | 中文响应式详情 UI | Hermes/Docker 表头中文化、横向滚动、宽 Profile 弹窗、移动端布局和状态徽标 | 主机页、详情弹窗 | 无 | `web/index.html`, `web/js/app.js`, `web/css/app.css` | 无 | 否 | HS-001, HS-018 | 是 | P1 |
| HS-026 | 部署可配置性与稳健输出 | 支持可替换基础镜像、`WEB_PORT`、`SERVERSTATUS_USER`；修复 C++ 空列表 JSON 逗号并扩大 stats 缓冲区 | 部署及异常场景 | `Dockerfile.client`, `Dockerfile.server`, `docker-compose-*.yml`, `server/src/main.cpp` | 无 | stats JSON | 新增构建参数和环境变量 | HS-022 | 仅迁移仍适用于 Go 的部分 | P2 |

## 优先级定义

| 级别 | 定义 |
| --- | --- |
| P0 | 形成可运行的单主机采集、传输和核心硬件/Docker 面板所必需，或涉及密钥安全。 |
| P1 | Hermes 业务监控与完整用户体验，核心底座稳定后迁移。 |
| P2 | 能力扩展、运维 API、部署便利或可由 Go 原生机制替代的优化。 |

## 关联文档

- 架构边界：[ARCHITECTURE.md](ARCHITECTURE.md)
- API 与协议：[API_DIFF.md](API_DIFF.md)
- 前端差异：[UI_DIFF.md](UI_DIFF.md)
- 后端差异：[BACKEND_DIFF.md](BACKEND_DIFF.md)
- 配置与依赖：[CONFIG_DIFF.md](CONFIG_DIFF.md)、[DEPENDENCY.md](DEPENDENCY.md)
- 迁移顺序：[MIGRATION_PLAN.md](MIGRATION_PLAN.md)
