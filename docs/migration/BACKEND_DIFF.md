# HermesStatus 后端差异

## 目录

- [总览](#总览)
- [C++ Server](#c-server)
- [Client](#client)
- [Docker 模块](#docker-模块)
- [SMART 与 Temperature 模块](#smart-与-temperature-模块)
- [Hermes 模块](#hermes-模块)
- [Mount 与配置摘要模块](#mount-与配置摘要模块)
- [API 模块](#api-模块)
- [新增脚本与测试](#新增脚本与测试)
- [Go 2.0 映射](#go-20-映射)
- [关联文档](#关联文档)

## 总览

1.0 相对旧 C++ 基线共修改 18 个既有业务/部署文件，并新增 exporter、配置摘要及 4 个测试文件。没有新增 `.cpp` 或 `.h` 文件；C++ 变化集中于 `main.cpp`、`main.h` 和 `network.h`。

## C++ Server

| 文件 | 类型 | 变更 | 对应功能 | Go 迁移落点 |
| --- | --- | --- | --- | --- |
| `server/src/main.cpp` | 修改 cpp | 解析三段扩展 JSON 字符串；嵌入 stats；stats 缓冲区改 1 MiB；修复 servers/sslcerts 空列表和逗号；`CMain` 改堆分配 | HS-022, HS-026 | `server/model.go`, `server/tcp_server.go`, `server/app.go` |
| `server/src/main.h` | 修改 h | Client stats 增加 4 KiB hardware、32 KiB docker、32 KiB hermes 缓冲区 | HS-022 | Go `AgentStats` 和子结构类型 |
| `server/src/network.h` | 修改 h | `NET_MAX_PACKETSIZE` 1400 -> 65536 | HS-022 | Go 已允许 1 MiB；增加领域限额即可 |

迁移时不复制手工字符串拼接、固定 char buffer 或 JSON-in-string。Go 端应在反序列化时得到结构化数据，并由 `SnapshotStats()` 序列化。

## Client

| 文件 | 变更 | 对应功能 | 迁移建议 |
| --- | --- | --- | --- |
| `clients/client-psutil.py` | 新增宿主机 OS/CPU、hwmon、SMART、Docker Socket、Hermes 快照读取、JSON 裁剪和三字段上报 | HS-004 至 HS-009、HS-016、HS-022 | 第一阶段复用，调整上报 schema；第二阶段再评估 Go 化 |
| `clients/client-linux.py` | 支持 `SERVERSTATUS_USER`，并发送空三字段 | HS-022, HS-026 | 保持兼容，但此客户端不具备 Hermes 实际采集能力 |
| `clients/entrypoint.sh` | 后台启动 600 秒 exporter 循环 | HS-011 | 保留独立刷新节奏；未来可用单独进程/调度器替代 shell 循环 |

## Docker 模块

实现文件：`clients/client-psutil.py`。

- 直接连接 `DOCKER_SOCKET`。
- 调用 `GET /containers/json?all=1`。
- 手工解析 HTTP response 和 chunked body。
- 输出 running、total、limit、truncated、error 和容器清单。
- 只读取列表 API，不 inspect；容器挂载点来自 Hermes 配置，不是 Docker 实际状态。

对应 HS-009。Go 迁移可先保留 Python 实现；若后续 Go 化，应使用稳定 Docker client/HTTP 层并维持只读 Socket。

## SMART 与 Temperature 模块

实现文件：`clients/client-psutil.py`、`scripts/export-hermes-status.py`。

| 数据点 | 主数据源 | 兜底 | 输出字段 |
| --- | --- | --- | --- |
| CPU 温度 | `/sys/class/hwmon/hwmon*/temp*_input` | 无 | `cpu_temperature` |
| SMART 健康 | `smartctl -x -j` / `smartctl -x` overall-health | SMART JSON flags | `disk_smart_status` |
| 硬盘温度 | Device Statistics page `0x05` offsets `0x008/0x020/0x028` | SMART temperature/current、hwmon disk | `disk_temperature.current/highest/lowest` |
| 通电小时 | Device Statistics `0x01/0x010` | SMART attribute 9 | `disk_power_on_hours` |
| 写入量 | Logical Sectors Written `0x01/0x018` × sector size | SMART LBA fields | `disk_written_bytes` |
| 读取量 | Logical Sectors Read `0x01/0x028` × sector size | SMART LBA fields | `disk_read_bytes` |

对应 HS-005 至 HS-008。两份实现存在重复，见 [LEGACY.md](LEGACY.md)。

## Hermes 模块

主实现：`scripts/export-hermes-status.py`。

| 子模块 | 行为 | 对应功能 |
| --- | --- | --- |
| Profile 注册 | 加载 `hermes-exporter.json`，规范化名称/路径/API | HS-010 |
| API 客户端 | loopback URL、Bearer Token、超时、错误收集 | HS-012, HS-021 |
| CLI 状态 | 调用 `hermes -p <profile> status`，必要时 `nsenter` 到宿主机 | HS-013, HS-014 |
| 版本 | `hermes --version`，进程内缓存 | HS-017 |
| Jobs | `/api/jobs`，提取启用、schedule、last status 等 | HS-015 |
| Sessions | `/api/sessions` 分页，汇总 usage | HS-015, HS-016 |
| Capabilities | models/capabilities/skills/toolsets | HS-020 及未展示的 P2 数据 |
| 本地回退 | Profile logs/run JSON 统计前一天任务和 token | HS-015, HS-016 |
| 快照 | 每 Profile 一个 JSON，临时文件 replace 原子写入 | HS-011 |

`clients/client-psutil.py` 再读取快照并只挑选 WebUI 所需字段上报。jobs/sessions 明细、capabilities 和 runs 没有穿透到最终 stats；runs 目前恒为空。

## Mount 与配置摘要模块

主实现：`scripts/hermes_config_summary.py`。

- 优先读取显式 `config_path`，再查 Profile 级环境变量和标准候选路径。
- PyYAML 可用时完整解析；否则使用简化 YAML parser。
- 读取主模型、11 个辅助模型键、Delegation、运行开关和 `terminal.docker_volumes`。
- 辅助项仅在 `provider:auto` 且 `model` 为空时继承主模型；其他情况显示自身配置。
- 对 api_key/token/secret/password/credential/auth 仅输出 `*_configured` 与 source，不输出值。

对应 HS-018、HS-019、HS-021。

## API 模块

| 文件 | 变更 | 对应功能 | 迁移结论 |
| --- | --- | --- | --- |
| `server/manage_api.py` | stats 路径改由 `WEB_DIR` 推导；新增 Profile 查询；移除 reset-traffic 实现 | HS-024 | Go 2.0 只需评估新增只读端点；不要迁移已移除 reset 逻辑 |
| `server/entrypoint-server.sh` | 向管理 API 传 `WEB_DIR` | HS-024 | Go 单进程不需要该桥接 |
| `server/nginx-serverstatus.conf` | `/` 增加 `Cache-Control: no-store` | HS-011, HS-026 | Go HTTP middleware/static handler 实现 |

完整 URL 差异见 [API_DIFF.md](API_DIFF.md)。

## 新增脚本与测试

| 文件 | 类型 | 覆盖范围 | 是否迁移 |
| --- | --- | --- | --- |
| `scripts/export-hermes-status.py` | 新增脚本 | Hermes API/CLI、本地回退、SMART、快照 | 是；首阶段复用 |
| `scripts/hermes_config_summary.py` | 新增脚本 | YAML 摘要、继承、脱敏、挂载 | 是；首阶段复用 |
| `scripts/tests/test_hermes_api_security.py` | 新增测试 | Token、loopback、分页 usage、MoA、版本 | 是，迁移后保留行为测试 |
| `scripts/tests/test_hermes_config_summary.py` | 新增测试 | 路径优先级、辅助继承、脱敏、异常 YAML | 是 |
| `scripts/tests/test_hermes_export_config.py` | 新增测试 | 自定义 Profile 名称/路径/API | 是 |
| `scripts/tests/test_payload_limits.py` | 新增测试 | Docker/Hermes 裁剪和 64 KiB wire limit | 改写为 Go schema/limit 集成测试 |

## Go 2.0 映射

| 1.0 责任 | 2.0 现有文件 | 缺口 |
| --- | --- | --- |
| TCP 解码 | `server/tcp_server.go` | `AgentStats` 未定义三组对象；未知字段被丢弃 |
| 数据模型 | `server/model.go` | 缺少 Hardware/Docker/Hermes 类型、验证与限额 |
| 内存状态/快照 | `server/app.go` | `SnapshotStats()` 未映射定制字段，也无域级 freshness |
| HTTP | `server/http_server.go` | stats URL 已有；缺 Hermes summary 路由/schema |
| OpenAPI | `server/openapi.go` | 未描述 HermesStatus 只读字段 |
| 静态服务 | `server/http_server.go` | 可承载定制 UI，无需 Nginx |
| 客户端 | `clients/client-psutil.py` | 2.0 分支是原生版本，需要移植 1.0 采集逻辑 |

## 关联文档

- 架构：[ARCHITECTURE.md](ARCHITECTURE.md)
- 功能：[FEATURE_MATRIX.md](FEATURE_MATRIX.md)
- 配置：[CONFIG_DIFF.md](CONFIG_DIFF.md)
- 依赖：[DEPENDENCY.md](DEPENDENCY.md)
- 迁移计划：[MIGRATION_PLAN.md](MIGRATION_PLAN.md)
