# HermesStatus API 与协议差异

## 目录

- [比较口径](#比较口径)
- [HermesStatus 自有 HTTP API](#hermesstatus-自有-http-api)
- [stats JSON 差异](#stats-json-差异)
- [客户端 TCP 协议](#客户端-tcp-协议)
- [外部 Hermes API 依赖](#外部-hermes-api-依赖)
- [Docker API 依赖](#docker-api-依赖)
- [2.0 兼容性结论](#20-兼容性结论)
- [关联文档](#关联文档)

## 比较口径

- “1.0”指当前 C++ HermesStatus 行为。
- “2.0”指当前 Go 分支基线，不代表完成迁移后的目标行为。
- `Compatible` 表示旧调用方无需修改或仅接收新增可选字段。
- `Breaking Change` 表示 URL、响应结构、语义或传输模型需要调用方/实现方同步修改。

## HermesStatus 自有 HTTP API

| 状态 | URL | Method | 参数/认证 | 1.0 返回 JSON/语义 | 2.0 当前状态 | 影响范围 | 兼容性 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 修改 | `/json/stats.json` | GET | 无；no-store | 原生 `servers[]` 中新增 `hardware`, `docker`, `hermes` 对象 | URL 保留，但 Go `AgentStats` 不接收也不输出三对象 | WebUI、客户端、持久化快照 | Breaking Change（功能字段丢失） |
| 新增 | `/api/hermes/config-summary` | GET | `profile` 可选；Bearer `ADMIN_TOKEN` | `{"ok":true,"profiles":[{"server","profile","config_summary"}]}` | 路由不存在 | 运维集成；当前 WebUI 不调用 | Breaking Change |
| 修改 | `/api/schema` | GET | 无 | endpoint 列表包含 Hermes config-summary，不含 reset-traffic | Go 2.0 含 OpenAPI 与 reset-traffic，不含 Hermes config-summary | API 发现客户端 | Breaking Change（schema 内容） |
| 修改 | `/api/health` | GET | 无 | `{"ok", "enabled", "sergate":{"running","pid"}, "configPath"}` | `{"ok","enabled","service":...,"agent":...,"configPath"}` | 健康检查与运维脚本 | Breaking Change（响应结构） |
| 修改 | `/api/restart` | POST | Bearer | 对 C++ `sergate` 发 `SIGTERM`，监督脚本重启子进程 | Go 进程内 Reload，返回 `mode:"in-process"` | 运维语义 | Breaking Change（语义） |
| 修改 | `/api/reload` | POST | Bearer | 对 C++ `sergate` 发 `SIGHUP` | Go 内存中重新加载配置并递增 generation | 运维语义基本一致 | Compatible（需更新响应断言） |
| 删除于 1.0 定制 | `/api/servers/{username}/reset-traffic` | POST | Bearer | 当前 1.0 路由已移除 | Go 2.0 恢复并原生实现 | 旧版配置 UI；当前 1.0 UI 不可达 | Compatible for 2.0，但不是 Hermes 定制迁移项 |
| 2.0 新增 | `/api/openapi.json` | GET | 无 | 1.0 不存在 | OpenAPI 3.1 | API Agent/开发工具 | Compatible（新增） |

其余 `/api/config`、`/api/servers`、`/api/monitors`、`/api/sslcerts`、`/api/watchdog` CRUD 在两个版本均存在，但 Go 2.0 的字段校验、错误 details 和配置重载实现不同。HermesStatus 当前页面只展示“主机”，没有调用这些 CRUD。

## stats JSON 差异

1.0 在单个 `servers[]` 节点中增加以下结构：

```json
{
  "hardware": {
    "cpu_model": "Intel Celeron J4125",
    "cpu_temperature": {"value": 42, "unit": "C", "source": "coretemp Package id 0"},
    "disk_temperature": {"current": 33, "highest": 33, "lowest": 33, "unit": "C"},
    "disk_smart_status": "passed",
    "disk_power_on_hours": 21399,
    "disk_written_bytes": 3226972519424,
    "disk_read_bytes": 1905003499520
  },
  "docker": {
    "running": 4,
    "total": 4,
    "containers": []
  },
  "hermes": {
    "profiles": []
  }
}
```

变更属于 JSON 层面的可选字段扩展，对能忽略未知字段的读取方是 `Compatible`；但 Go 2.0 强类型反序列化会直接丢弃未声明字段，因此从迁移角度属于功能性 `Breaking Change`。完整字段见 [CONFIG_DIFF.md](CONFIG_DIFF.md)。

## 客户端 TCP 协议

| 项目 | 原生/2.0 当前 | 1.0 HermesStatus | 兼容性 |
| --- | --- | --- | --- |
| 命令 | `update {JSON}\n` | 不变 | Compatible |
| 新字段 | 无 | `hardware_json`, `docker_json`, `hermes_json`，值为压缩后的 JSON 字符串 | 旧 C++ 基线通常忽略未知字段；Go 2.0 会忽略，导致功能丢失 |
| 最大请求 | C++ 原基线 1400 字节；Go scanner 1 MiB | C++ 提升至 65536 字节 | Go 容量 Compatible；仍需域级限额 |
| 服务端存储 | 强类型基础指标 | C++ 固定缓冲区：4 KiB/32 KiB/32 KiB | 迁移时应改为 Go 结构体，不延续 JSON-in-string |
| 输出 | 基础字段 | 将三段字符串解析前提下原样嵌入 stats | 需要 Go 快照映射 |

迁移目标建议将字段升级为结构化对象，例如 `hardware`, `docker`, `hermes`，同时在服务端执行长度、数组数量和字符串长度验证。对应功能为 HS-022。

## 外部 Hermes API 依赖

这些 URL 是客户端 exporter 调用的 Hermes Agent API，不是 HermesStatus 对外提供的 API。

| URL | Method | 参数 | 使用数据 | HermesStatus 输出 | 兼容性要求 |
| --- | --- | --- | --- | --- | --- |
| `/health` | GET | Bearer | status/state/health、usage、provider、running_agents | 服务/API 状态与 usage 兜底 | P0 依赖；401/连接失败必须降级 |
| `/health/detailed` | GET | Bearer | detailed health、usage、provider、资源字段 | 服务详情与 usage 兜底 | Compatible，字段按可选处理 |
| `/api/jobs` | GET | Bearer | 任务、schedule、enabled/paused、last status、provider/model | 活动/总任务数；详情仅存在 exporter 快照 | P1 |
| `/api/sessions` | GET | `limit`, `offset`; Bearer | sessions、分页、session usage | 活动/总会话与 usage 汇总 | P1；必须处理分页 |
| `/v1/models` | GET | Bearer | 模型列表 | exporter capabilities，当前 UI 不展示 | P2 |
| `/v1/capabilities` | GET | Bearer | API 能力 | exporter capabilities，当前 UI 不展示 | P2 |
| `/v1/skills` | GET | Bearer | skills | exporter capabilities，当前 UI 不展示 | P2 |
| `/v1/toolsets` | GET | Bearer | toolsets/tools | Mixture of Agents | P2 |

当前代码**没有**调用 `POST /v1/chat/completions`、`POST /v1/responses`、`POST /v1/runs`、`GET /v1/runs/{id}` 或 events/stop/approval。`profile_stats()` 固定输出 `"runs": []`。因此这些不能被登记为现有能力；若 2.0 要提供 Runs 操作，应作为新需求单独设计，不应伪装成 1.0 等价迁移。

Token 当前来自 API payload 中递归识别的 usage，以及本地日志兜底；后者标记 `estimated`。它不是稳定的全局/月度成本账本。

## Docker API 依赖

| URL | Method | 传输 | 返回使用字段 | 兼容性 |
| --- | --- | --- | --- | --- |
| `/containers/json?all=1` | GET | `/var/run/docker.sock` Unix Socket 上的 HTTP/1.1 | `Id`, `Image`, `Command`, `Created`, `Status`, `State`, `Ports`, `Names` | 依赖 Docker Engine API 的兼容字段；失败时返回空列表和 error |

当前实现手工解析 HTTP 和 chunked body，没有使用 Docker SDK，也没有调用 inspect，因此 Profile 详情中的挂载点来自 Hermes `config.yaml`，不是 Docker API 的实际 Mounts。

## 2.0 兼容性结论

1. Go 2.0 的 1 MiB TCP scanner 可以容纳当前负载，但数据模型和快照映射缺失，是首要迁移阻断点。
2. `/json/stats.json` 应保持新增字段为可选对象，避免破坏原生 WebUI 和旧客户端。
3. `/api/hermes/config-summary` 是否保留应先确认调用者；当前 UI 直接读取 stats，API 可能降级为 P2 或废弃候选。
4. Hermes API 应继续由客户端后端代理访问，浏览器不得得到 API Key 或直接访问 8642-8644。
5. Go 2.0 的 `/api/openapi.json` 应扩展 Hermes 只读响应 schema，但不应包含任何 secret 字段。

## 关联文档

- 功能编号：[FEATURE_MATRIX.md](FEATURE_MATRIX.md)
- 架构：[ARCHITECTURE.md](ARCHITECTURE.md)
- 配置字段：[CONFIG_DIFF.md](CONFIG_DIFF.md)
- 遗留与缺口：[LEGACY.md](LEGACY.md)
