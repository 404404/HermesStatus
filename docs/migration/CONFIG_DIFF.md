# HermesStatus 配置差异

## 目录

- [结论](#结论)
- [新增配置文件](#新增配置文件)
- [新增环境变量](#新增环境变量)
- [动态 Profile API 变量](#动态-profile-api-变量)
- [新增 JSON 字段](#新增-json-字段)
- [Hermes config.yaml 读取范围](#hermes-configyaml-读取范围)
- [Docker Compose 挂载与权限](#docker-compose-挂载与权限)
- [Go 2.0 保留策略](#go-20-保留策略)
- [关联文档](#关联文档)

## 结论

项目没有数据库，也没有数据库 schema 变更。新增状态由 JSON 配置、环境变量、只读宿主机挂载和临时/持久化 JSON 快照组成。

## 新增配置文件

| 文件 | 主要字段 | 作用 | 迁移后是否保留 |
| --- | --- | --- | --- |
| `hermes-exporter.json` | `hermes_root`, `status_dir`, `profiles[]` | HermesStatus 采集注册表 | 是，HS-010；可保持独立配置或并入专用 HermesStatus 配置段 |
| `hermes-exporter.json.profiles[]` | `name`, `profile_dir`, `config_path`, `env_path`, `api` | 每个 Profile 独立路径和 API | 是；禁止重新硬编码 hermes1/2/3 |
| `server/config.json` | 单个 J4125 server，空 monitors/sslcerts | 单主机 ServerStatus 示例 | 保留部署实例值，不把 LAN IP/密码作为通用默认；Release C 不含告警配置 |
| `hermes-status/*.json` | Profile 快照与 `hardware.json` | exporter 与 client 之间的状态交换 | 首阶段保留；后续可由进程内共享/IPC 取代 |

示例 Profile API 配置：

```json
{
  "name": "hermes1",
  "profile_dir": "/home/hermes/hermes1",
  "config_path": "/home/hermes/.hermes/profiles/hermes1/config.yaml",
  "env_path": "/home/hermes/hermes1/.env",
  "api": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8642
  }
}
```

## 新增环境变量

| 变量 | 默认值 | 用途 | Go 迁移后 |
| --- | --- | --- | --- |
| `SERVERSTATUS_USER` | `s01` | 避免宿主机 `$USER` 覆盖客户端账号 | 保留或统一修正 Compose 变量名 |
| `HERMES_EXPORT_CONFIG` | `/app/hermes-exporter.json` | 容器内注册表路径 | 保留 |
| `HERMES_ROOT` | `/home/hermes` | Hermes 宿主机根目录 | 保留 |
| `HERMES_STATUS_DIR` | `/hermes/status` | 快照目录 | 首阶段保留 |
| `HARDWARE_STATUS_FILE` | `/hermes/status/hardware.json` | 硬件快照路径 | 首阶段保留 |
| `HERMES_EXPORT_ENABLED` | `true` | 是否启动 exporter | 保留 |
| `HERMES_EXPORT_INTERVAL` | `600` | exporter 间隔秒数 | 保留，建议类型化校验 |
| `HOST_OS_RELEASE_FILE` | `/host/etc/os-release` | 宿主机发行版文件 | 保留 |
| `SMART_DEVICE` | `/dev/sda` | SMART 目标；代码支持 `auto` | 保留 |
| `DOCKER_SOCKET` | `/var/run/docker.sock` | Docker Engine Socket | 保留 |
| `DOCKER_CONTAINER_LIMIT` | `0` | 容器列表最大行数，0 表示全部 | 保留并设置合理上限 |
| `DOCKER_JSON_MAX_BYTES` | `12000` | Docker JSON 上报字节限额 | 改为 Go 结构/数组限额，兼容读取旧值 |
| `HERMES_JSON_MAX_BYTES` | Dockerfile `26000` | Hermes JSON 上报字节限额 | 改为 Go 结构/数组限额；统一代码默认值差异 |
| `HERMES_API_TIMEOUT` | `2.5` | Hermes API 请求超时 | 保留 |
| `HERMES_EXPORT_TABLE_LIMIT` | `20` | jobs/sessions/capabilities 最大保留行数 | 保留 |
| `HERMES_API_PAGE_LIMIT` | `100` | sessions 分页大小 | 保留 |
| `HERMES_API_MAX_PAGES` | `100` | sessions 最大页数 | 保留并降低风险上限 |
| `HERMES_HOST_USER` | `hermes` | `nsenter` 后执行 CLI 的宿主机用户 | 保留，仅在 CLI 路径使用 |
| `WEB_PORT` | `8080` | 服务端宿主机 Web 端口 | 保留 Compose 可配置性 |
| `CLIENT_ALPINE_IMAGE` | `alpine:3.13` | 客户端构建基础镜像 | 可删除或更新为 2.0 统一版本 |
| `SERVER_PYTHON_IMAGE` | `python:3.12-slim-bookworm` | C++ builder 基础镜像 | 删除；Go builder 取代 |
| `SERVER_DEBIAN_IMAGE` | `debian:bookworm-slim` | C++ runtime 基础镜像 | 删除；Go 2.0 Alpine runtime 取代 |
| `ADMIN_TOKEN` | 空 | ServerStatus 管理 API | Go 2.0 原生保留 |

Compose 宿主机路径变量：

| 变量 | 默认值 | 保留 |
| --- | --- | --- |
| `HERMES_EXPORT_CONFIG_HOST` | `./hermes-exporter.json` | 是 |
| `HERMES_ROOT_HOST` | `/home/hermes` | 是 |
| `HERMES_STATUS_DIR_HOST` | `./hermes-status` | 首阶段是 |

## 动态 Profile API 变量

Exporter 还支持按 Profile 派生的变量，Profile 名会转为大写并把非字母数字替换为下划线：

| 模式 | 示例 | 说明 | 保留策略 |
| --- | --- | --- | --- |
| `HERMES_API_ENABLED_<PROFILE>` | `HERMES_API_ENABLED_HERMES1` | Profile API 开关 | 保留但以注册表为主 |
| `API_SERVER_ENABLED_<PROFILE>` | `API_SERVER_ENABLED_HERMES1` | Hermes 命名兼容 | 兼容保留 |
| `HERMES_API_BASE_URL_<PROFILE>` | `HERMES_API_BASE_URL_HERMES1` | Profile 完整 URL | 保留 |
| `HERMES_API_TOKEN_<PROFILE>` | `HERMES_API_TOKEN_HERMES1` | Profile Token | 保留，secret-only |
| `API_SERVER_KEY_<PROFILE>` | `API_SERVER_KEY_HERMES1` | Hermes 命名兼容 | 保留，secret-only |
| `<PROFILE>_API_SERVER_KEY` | `HERMES1_API_SERVER_KEY` | 历史命名兼容 | P2 兼容后可废弃 |
| 全局 `API_SERVER_ENABLED`, `API_SERVER_HOST`, `API_SERVER_PORT`, `API_SERVER_KEY` | Profile `.env` | Hermes 官方 API Server 配置 | 读取保留；host `0.0.0.0/::` 访问时强制改用 loopback |
| `HERMES_CONFIG_PATH_<PROFILE>` | `HERMES_CONFIG_PATH_HERMES1` | Profile config.yaml 覆盖 | 保留 |
| `HERMES_CONFIG_PATH` | 任意路径 | 全局 config.yaml 覆盖 | 保留，优先级低于显式 Profile config_path |

Token 不得写入 stats、日志、HTML、OpenAPI 示例或管理 API 响应。

## 新增 JSON 字段

### Client `update` payload

| 字段 | 类型 | 说明 | 迁移 |
| --- | --- | --- | --- |
| `hardware_json` | string(JSON) | 硬件健康对象 | 改为结构化 `hardware` |
| `docker_json` | string(JSON) | 容器汇总与列表 | 改为结构化 `docker` |
| `hermes_json` | string(JSON) | Profiles 数组 | 改为结构化 `hermes` |

### `hardware`

| 字段 | 类型 | 保留 |
| --- | --- | --- |
| `cpu_model` | string | 是 |
| `cpu_temperature` | object/null: `value`, `unit`, `source` | 是 |
| `disk_temperature` | object/null: `value/current/highest/lowest/unit/source` | 是 |
| `disk_smart_status` | `passed/failed/unknown` | 是 |
| `disk_power_on_hours` | integer/null | 是 |
| `disk_written_bytes`, `disk_read_bytes` | integer/null | 是 |
| `disk_device`, `disk_smart_source` | string/null | 保留在 API，UI 可不显示 |
| `updated_at` | timestamp | 是；用于 stale 判断 |

### `docker`

| 字段 | 类型 | 保留 |
| --- | --- | --- |
| `running`, `total` | integer | 是 |
| `limit` | integer | 是 |
| `truncated` | boolean | 是 |
| `error` | string 可选 | 是，但对外应限制长度 |
| `containers[]` | object[] | 是 |
| container `names/image/status/ports` | string | 是；Release C 固定四字段 |

### `hermes.profiles[]`

| 字段组 | 字段 | 保留策略 |
| --- | --- | --- |
| 身份 | `profile`, `agent_version` | 保留 |
| 状态 | `api_status`, `service_status`, `gateway_service`, `manager_mode` | 保留 |
| 模型 | `usage_mode`, `provider`, `model`, `auth_refreshed_at` | 保留 |
| 任务/会话 | `scheduled_jobs_active/total`, `sessions_active/total`, `sessions_has_more` | 保留 |
| usage | `input_tokens`, `output_tokens`, `total_tokens`, `estimated` | 保留并明确统计窗口 |
| 详情 | `mixture_of_agents`, `config_summary` | 保留 |
| 未显示 | `running_agents`, `resource_status`, `note`, `last_run_at`, `yesterday_*` | 先记录；按 [LEGACY.md](LEGACY.md) 评估 |
| 被裁掉 | exporter 的 `jobs`, `sessions`, `runs`, `capabilities` | 当前最终 stats 不含，不能视为现有 UI 合同 |

## Hermes config.yaml 读取范围

| 路径 | 用途 | 保留 |
| --- | --- | --- |
| `model.*` | 主模型 Provider/Model/Base URL 和 secret configured 标记 | 是 |
| `auxiliary.vision` | 辅助模型 | 是 |
| `auxiliary.web_extract` | 辅助模型 | 是 |
| `auxiliary.compression` | 辅助模型 | 是 |
| `auxiliary.skills_hub` | 辅助模型 | 是 |
| `auxiliary.approval` | 辅助模型 | 是 |
| `auxiliary.mcp` | 辅助模型 | 是 |
| `auxiliary.title_generation` | 辅助模型 | 是 |
| `auxiliary.triage_specifier` | 辅助模型 | 是 |
| `auxiliary.kanban_decomposer` | 辅助模型 | 是 |
| `auxiliary.profile_describer` | 辅助模型 | 是 |
| `auxiliary.curator` | 辅助模型 | 是 |
| `terminal.docker_volumes` | 容器挂载点 | 是 |
| `delegation.*` | Delegation 详情 | 是 |
| `toolsets`, `platform_toolsets`, `approvals`, `compression`, `memory`, `curator`, `timezone` | 运行摘要 | P1/P2 按 UI 需要保留 |

辅助模型有效值规则：仅当 `provider == auto` 且 `model` 为空时继承主模型；否则使用自身 provider/model，即使 model 为空也显示 Provider default。

## Docker Compose 挂载与权限

| 挂载/设置 | 目的 | 迁移后 |
| --- | --- | --- |
| `/sys/class/hwmon:ro` | 温度 | 保留 |
| `/etc/os-release:/host/etc/os-release:ro` | 宿主机发行版 | 保留 |
| `/var/run/docker.sock:ro` | Docker API | 保留；说明 Socket 本身仍具有高权限风险 |
| `/dev:ro` + `privileged:true` | SMART 设备访问 | 先保留验证，再评估最小 device/capability |
| Hermes root `:ro` | CLI 配置/env/logs | 保留，只读 |
| status dir `:rw` | exporter 快照 | 首阶段保留 |
| `network_mode:host` | 访问 127.0.0.1:8642-8644 | 保留，或后续改显式 host gateway/Unix Socket |
| `pid:host` | `nsenter` 宿主机执行 Hermes CLI | 仅在 CLI 路径需要，后续评估移除 |

## Go 2.0 保留策略

1. 保留用户级路径、Profile 注册、API URL/token、刷新频率和设备选择配置。
2. 删除 C++ server build image/CFLAGS 配置；Go 2.0 已由 `go.mod` 与 Go Docker builder 管理。
3. 将字节字符串限额转成 Go 类型验证，同时兼容旧环境变量一个过渡版本。
4. 不把 HermesStatus 字段混入 ServerStatus `server/config.json` 的节点 schema；建议独立配置，以免破坏原生 API/OpenAPI。
5. 为所有快照增加 schema version，便于 Python collector 与 Go server 独立升级。

## 关联文档

- 功能：[FEATURE_MATRIX.md](FEATURE_MATRIX.md)
- API：[API_DIFF.md](API_DIFF.md)
- 后端：[BACKEND_DIFF.md](BACKEND_DIFF.md)
- 依赖：[DEPENDENCY.md](DEPENDENCY.md)
