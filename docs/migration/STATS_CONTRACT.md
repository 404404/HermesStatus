# HermesStatus Stats 数据合同

## 目录

- [合同范围](#合同范围)
- [通用约定](#通用约定)
- [根对象](#根对象)
- [hardware](#hardware)
- [docker](#docker)
- [dockercontainers](#dockercontainers)
- [hermes](#hermes)
- [hermesprofiles](#hermesprofiles)
- [Token usage](#token-usage)
- [错误合同](#错误合同)
- [updated_at 与 stale](#updated_at-与-stale)
- [输出权限](#输出权限)
- [Secret 禁止规则](#secret-禁止规则)
- [兼容规则](#兼容规则)
- [关联文档](#关联文档)

## 合同范围

本合同只定义附加到 ServerStatus 原生 Agent update 和单节点 stats 上的 HermesStatus 扩展对象，不复制 CPU、内存、磁盘、网络等原生 schema。对应 JSON Schema：

- [agent-update-extension.schema.json](schema/agent-update-extension.schema.json)
- [stats-extension.schema.json](schema/stats-extension.schema.json)

Release A 实现范围是 HS-004 至 HS-011、HS-021、HS-022、HS-023。Profile 中的 P1 字段和 `config_summary.docker_volumes` 仅用于固定兼容外形和边界测试，不代表 Release A 实现 P1/P2 采集或 UI。

## 通用约定

| 项目 | 规则 |
| --- | --- |
| 时间 | RFC 3339，建议 UTC `Z`；最大 40 字符 |
| 空值 | 数据源没有可靠值时使用 `null`，不得用 `0` 冒充未知数值 |
| 空集合 | 使用 `[]`，不使用 `null` |
| 未知状态 | 使用明确枚举 `unknown`/`unavailable`，不省略必填状态字段 |
| 数值 | 计数和字节数为非负整数；温度为摄氏度 number |
| 未知字段 | 所有合同对象 `additionalProperties: false`，防止上游响应或 secret 被透传 |
| 降级 | 保留最后有效值时必须保留其原 `updated_at`；同时设置结构化 `error` |
| stale | Agent 可发送提示值，Go 服务端输出前必须按本合同重新计算 |
| 日志 | 只记录结构化 code/source 和必要计数，不记录原始 payload 或上游响应体 |

## 根对象

### Agent update 扩展

| 字段 | JSON 类型 | 必填 | null | 默认值 | 字符串上限 | 数组上限 | 来源 | 允许日志 | stats | OpenAPI | 浏览器 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `extension_version` | string | 是 | 否 | `1.0-draft` | 32 | 不适用 | collector 常量 | 是 | 是 | 是，仅 Schema/示例 | 是 |
| `hardware` | object | 是 | 否 | 空降级对象 | 不适用 | 不适用 | 宿主机采集 | 仅状态 | 是 | 是 | 是 |
| `docker` | object | 是 | 否 | 空集合对象 | 不适用 | 不适用 | Docker Socket | 仅状态/计数 | 是 | 是 | 是 |
| `hermes` | object | 是 | 否 | 空 Profile 对象 | 不适用 | 不适用 | exporter 快照 | 仅状态/计数 | 是 | 是 | 是 |

### Stats 扩展

Stats 扩展在同样对象上增加服务端接收时间：

| 字段 | JSON 类型 | 必填 | null | 默认值 | 字符串上限 | 数组上限 | 来源 | 允许日志 | stats | OpenAPI | 浏览器 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `received_at` | string | 是 | 否 | 无 | 40 | 不适用 | Go 服务端接受有效 update 的时间 | 是 | 是 | 是 | 是 |

`received_at` 不能替代域级 `updated_at`；服务端每秒生成 stats 也不能刷新域级时间。

## hardware

| 字段 | JSON 类型 | 必填 | null | 默认值 | 字符串上限 | 数组上限 | 数据来源 | updated_at/stale/error 规则 | 日志 | stats/OpenAPI/浏览器 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `cpu_model` | string/null | 是 | 是 | `null` | 128 | 不适用 | `lscpu --json`，兜底 `/proc/cpuinfo` | 归属 hardware 时间 | 是，脱敏后 | 是/是/是 |
| `cpu_temperature` | object/null | 是 | 是 | `null` | source 128 | 不适用 | `/sys/class/hwmon` | 缺传感器可为 null，不等同 error | 数值可记录 | 是/是/是 |
| `disk_temperature` | object/null | 是 | 是 | `null` | source 128 | 不适用 | SMART Device Statistics，兜底 SMART/hwmon | current/highest/lowest 可分别 null | 数值可记录 | 是/是/是 |
| `disk_smart_status` | string enum | 是 | 否 | `unknown` | 7 | 不适用 | `smartctl -x` overall-health | 执行失败必须 `unknown` + error | 是 | 是/是/是 |
| `disk_power_on_hours` | integer/null | 是 | 是 | `null` | 不适用 | 不适用 | Device Statistics `0x01/0x010`，兜底属性 9 | 未读取时 null | 是 | 是/是/是 |
| `disk_written_bytes` | integer/null | 是 | 是 | `null` | 不适用 | 不适用 | Logical Sectors Written × sector size | 未读取时 null | 是 | 是/是/是 |
| `disk_read_bytes` | integer/null | 是 | 是 | `null` | 不适用 | 不适用 | Logical Sectors Read × sector size | 未读取时 null | 是 | 是/是/是 |
| `disk_device` | string/null | 是 | 是 | `null` | 128 | 不适用 | smartctl 选中的设备 | 不允许包含命令或参数 | 否 | 是/是/是 |
| `disk_smart_source` | string/null | 是 | 是 | `null` | 64 | 不适用 | `smartctl-json`/`smartctl-text` 等固定标签 | 不允许原始输出 | 是 | 是/是/是 |
| `updated_at` | string/null | 是 | 是 | `null` | 40 | 不适用 | 最近一次 hardware 采集完成时间 | null 必须 stale | 是 | 是/是/是 |
| `stale` | boolean | 是 | 否 | `true` | 不适用 | 不适用 | 服务端重新计算 | 见 freshness 规则 | 是 | 是/是/是 |
| `error` | object/null | 是 | 是 | `null` | 见错误合同 | 不适用 | collector/server | 不得含 raw output | 是，结构化 | 是/是/是 |

温度对象：

| 对象 | 字段 | 类型 | 必填/null | 默认 | 限制 |
| --- | --- | --- | --- | --- | --- |
| `cpu_temperature` | `value` | number | 是/否 | 无 | -100 至 250 |
| `cpu_temperature` | `unit` | string | 是/否 | `C` | 常量 `C` |
| `cpu_temperature` | `source` | string/null | 是/是 | `null` | 128 字符 |
| `disk_temperature` | `current`, `highest`, `lowest` | number/null | 是/是 | `null` | -100 至 250 |
| `disk_temperature` | `unit` | string | 是/否 | `C` | 常量 `C` |
| `disk_temperature` | `source` | string/null | 是/是 | `null` | 128 字符 |

## docker

| 字段 | JSON 类型 | 必填 | null | 默认值 | 字符串上限 | 数组上限 | 数据来源 | updated_at/stale/error 规则 | 日志 | stats/OpenAPI/浏览器 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `running` | integer | 是 | 否 | `0` | 不适用 | 不适用 | Docker `/containers/json?all=1` | 必须 `<= total` | 是 | 是/是/是 |
| `total` | integer | 是 | 否 | `0` | 不适用 | 不适用 | 同上 | 采集失败不得伪造成功，需 error | 是 | 是/是/是 |
| `limit` | integer | 是 | 否 | `0` | 不适用 | 不适用 | collector 配置 | `0` 表示未主动截断 | 是 | 是/是/是 |
| `truncated` | boolean | 是 | 否 | `false` | 不适用 | 不适用 | collector | 列表数量小于 total 时为 true | 是 | 是/是/是 |
| `containers` | array | 是 | 否 | `[]` | 见子对象 | 256 | Docker API allowlist | 失败时空数组 + error | 仅数量 | 是/是/是 |
| `updated_at` | string/null | 是 | 是 | `null` | 40 | 不适用 | Docker API 返回并解析完成时间 | null 必须 stale | 是 | 是/是/是 |
| `stale` | boolean | 是 | 否 | `true` | 不适用 | 不适用 | 服务端重新计算 | 见 freshness 规则 | 是 | 是/是/是 |
| `error` | object/null | 是 | 是 | `null` | 见错误合同 | 不适用 | collector/server | 不得含 Socket 原始响应 | 是，结构化 | 是/是/是 |

## docker.containers[]

| 字段 | JSON 类型 | 必填 | null | 默认值 | 最大字符串 | 最大数组 | 数据来源 | 日志 | stats | OpenAPI | 浏览器 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | 否 | `-` | 64 | 不适用 | Docker `Id`，建议 12 字符显示值 | 否 | 是 | 是 | 是 |
| `names` | string | 是 | 否 | `-` | 256 | 不适用 | Docker `Names` 拼接 | 否 | 是 | 是 | 是 |
| `state` | string enum | 是 | 否 | `unknown` | 10 | 不适用 | Docker `State` | 是 | 是 | 是 | 是 |
| `status` | string | 是 | 否 | `unknown` | 128 | 不适用 | Docker `Status` | 否 | 是 | 是 | 是 |
| `created` | string | 是 | 否 | `-` | 64 | 不适用 | Docker `Created` 格式化 | 否 | 是 | 是 | 是 |
| `image` | string | 是 | 否 | `-` | 256 | 不适用 | Docker `Image` | 否 | 是 | 是 | 是 |
| `command` | string | 是 | 否 | `-` | 512 | 不适用 | Docker `Command` 经 secret sanitizer | **否** | 是 | 是 | 是 |
| `ports` | string | 是 | 否 | `-` | 512 | 不适用 | Docker `Ports` 格式化 | 否 | 是 | 是 | 是 |

`command` 必须先删除或替换疑似 secret 参数。若无法可靠脱敏，值必须改为 `[redacted]`，不能因为 1.0 曾显示原始命令而继续透传。

## hermes

| 字段 | JSON 类型 | 必填 | null | 默认值 | 字符串上限 | 数组上限 | 数据来源 | updated_at/stale/error 规则 | 日志 | stats/OpenAPI/浏览器 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `profiles` | array | 是 | 否 | `[]` | 见子对象 | 64 | 独立 exporter 注册表和快照 | 单 Profile error 不删除其他 Profile | 仅名称/计数 | 是/是/是 |
| `updated_at` | string/null | 是 | 是 | `null` | 40 | 不适用 | 本轮 exporter 完成时间 | null 必须 stale | 是 | 是/是/是 |
| `stale` | boolean | 是 | 否 | `true` | 不适用 | 不适用 | 服务端重新计算 | 任一 Profile stale 可与域 partial error 并存 | 是 | 是/是/是 |
| `error` | object/null | 是 | 是 | `null` | 见错误合同 | 不适用 | exporter/server | partial failure 使用固定 code | 是，结构化 | 是/是/是 |

## hermes.profiles[]

| 字段 | JSON 类型 | 必填 | null | 默认值 | 最大字符串 | 最大数组 | 数据来源 | 日志 | stats | OpenAPI | 浏览器 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `profile` | string | 是 | 否 | 无 | 64 | 不适用 | `hermes-exporter.json` name | 是 | 是 | 是 | 是 |
| `agent_version` | string/null | 是 | 是 | `null` | 64 | 不适用 | Hermes CLI；Release A 可为 null | 是 | 是 | 是 | 是 |
| `api_status` | string enum | 是 | 否 | `unknown` | 12 | 不适用 | Hermes health；Release A 仅兼容 | 是 | 是 | 是 | 是 |
| `service_status` | string/null | 是 | 是 | `null` | 64 | 不适用 | Hermes API/CLI；Release A 可为 null | 是 | 是 | 是 | 是 |
| `gateway_service` | string/null | 是 | 是 | `null` | 64 | 不适用 | Hermes CLI；Release A 可为 null | 是 | 是 | 是 | 是 |
| `manager_mode` | string/null | 是 | 是 | `null` | 96 | 不适用 | Hermes CLI；Release A 可为 null | 是 | 是 | 是 | 是 |
| `usage_mode` | string enum/null | 是 | 是 | `null` | 13 | 不适用 | Hermes CLI；Release A 可为 null | 是 | 是 | 是 | 是 |
| `provider` | string/null | 是 | 是 | `null` | 128 | 不适用 | Hermes CLI；Release A 可为 null | 否 | 是 | 是 | 是 |
| `model` | string/null | 是 | 是 | `null` | 256 | 不适用 | Hermes CLI/config；Release A 可为 null | 否 | 是 | 是 | 是 |
| `auth_refreshed_at` | string/null | 是 | 是 | `null` | 40 | 不适用 | 已登录 provider 的刷新时间 | 否 | 是 | 是 | 是 |
| `scheduled_jobs_active`, `scheduled_jobs_total` | integer/null | 是 | 是 | `null` | 不适用 | 不适用 | P1 API/CLI，Release A 不采集 | 仅计数 | 是 | 是 | 是 |
| `sessions_active`, `sessions_total` | integer/null | 是 | 是 | `null` | 不适用 | 不适用 | P1 API/CLI，Release A 不采集 | 仅计数 | 是 | 是 | 是 |
| `usage` | object | 是 | 否 | unavailable 对象 | 见 Token usage | 不适用 | P1/诊断兼容字段 | 否 | 是 | 是 | 是 |
| `config_summary` | object/null | 是 | 是 | `null` | volume 512 | volumes 64 | 仅允许 `docker_volumes` 投影；Release A 不展示 | 否 | 是 | 是 | 是 |
| `updated_at` | string/null | 是 | 是 | `null` | 40 | 不适用 | Profile 快照完成时间 | 是 | 是 | 是 | 是 |
| `stale` | boolean | 是 | 否 | `true` | 不适用 | 不适用 | 服务端重新计算 | 是 | 是 | 是 | 是 |
| `error` | object/null | 是 | 是 | `null` | 见错误合同 | 不适用 | exporter/server | 是，结构化 | 是 | 是 | 是 |

`config_summary` 在本合同中是严格 allowlist，只允许 `docker_volumes: string[]`。主模型、辅助模型、Delegation 等 HS-018/HS-019 数据将在 Release B 合同中单独扩展，不能通过 `additionalProperties` 偷渡。

## Token usage

| 字段 | JSON 类型 | 必填 | null | 默认值 | 最大值/字符串 | 数据来源 | 输出规则 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `input_tokens` | integer/null | 是 | 是 | `null` | 9,007,199,254,740,991 | Hermes usage 或诊断兜底 | 无可靠值必须 null |
| `output_tokens` | integer/null | 是 | 是 | `null` | 同上 | 同上 | 无可靠值必须 null |
| `total_tokens` | integer/null | 是 | 是 | `null` | 同上 | 同上或 input+output | 三项均存在时应等于 input+output |
| `estimated` | boolean | 是 | 否 | `true` | 不适用 | collector | 任何本地兜底或不稳定窗口必须 true |
| `source` | string enum | 是 | 否 | `unavailable` | 32 | `hermes_api_payload`, `local_session_state`, `local_logs`, `unavailable` | 不允许 endpoint、URL 或凭证 |
| `window_start` | string/null | 是 | 是 | `null` | 40 | 统计窗口 | 无稳定窗口必须 null |
| `window_end` | string/null | 是 | 是 | `null` | 40 | 统计窗口 | 与 start 同时为 null 或同时有值 |

Token usage 是 P1/诊断兼容字段，不是 Release A 的实现目标。合同约束：

1. `source == unavailable` 时三项 token 和两个窗口必须为 null，`estimated == true`。
2. 无法证明稳定窗口时，`window_start/window_end` 为 null，数据只可标记为 diagnostic；不得称为全局、日度或月度账本。
3. 本地日志/状态兜底必须 `estimated == true`。
4. 不允许从请求头、API Key 或原始消息内容推导或输出任何字段。

## 错误合同

所有域和 Profile 共用以下 `error` 对象；成功时为 null：

| 字段 | 类型 | 必填/null | 默认 | 限制 | 规则 |
| --- | --- | --- | --- | --- | --- |
| `code` | string | 是/否 | 无 | 64 字符，`^[a-z0-9_]+$` | 稳定机器码，如 `smartctl_unavailable`, `docker_unavailable`, `api_unauthorized`, `api_timeout`, `partial_failure`, `not_reported` |
| `message` | string | 是/否 | 无 | 256 字符 | 人类可读且已脱敏；不得包含命令输出、响应体、URL query 或 header |
| `source` | string | 是/否 | 无 | 64 字符 | 固定组件名，不是文件内容或命令行 |
| `retryable` | boolean | 是/否 | `false` | 不适用 | timeout/暂时不可达通常为 true |
| `http_status` | integer/null | 是/是 | `null` | 100-599 | 只记录状态码，不记录响应体 |

## updated_at 与 stale

| 对象 | stale 阈值 | 规则 |
| --- | --- | --- |
| `hardware` | 900 秒 | 覆盖 600 秒 SMART/exporter 周期及调度余量 |
| `docker` | 120 秒 | 1.0 通常随 client update 采集；两分钟无成功值视为陈旧 |
| `hermes` | 900 秒 | 覆盖 600 秒 exporter 周期及调度余量 |
| `hermes.profiles[]` | 900 秒 | 每 Profile 独立计算 |

服务端规则：

1. `updated_at == null` 时 `stale = true`。
2. `now - updated_at` 超过阈值时 `stale = true`。
3. `updated_at` 比服务端时间超前超过 300 秒时 `stale = true`，并使用安全 `clock_skew` error。
4. 最近一次采集失败但仍保留阈值内的 last-good 值时，`stale` 可为 false，`error` 非 null。
5. `received_at` 只代表服务端收包，不改变以上判断。

## 输出权限

| 介质 | 允许内容 | 禁止内容 |
| --- | --- | --- |
| 服务端日志 | code、source、HTTP 状态码、Profile 名、数组计数、长度 | 原始 update、container command、mount path、model/provider 值、上游 response body、任何 secret |
| stats | Schema 白名单且经过长度/secret sanitizer 的全部字段 | 未知字段、原始旧 JSON 字符串、secret |
| OpenAPI | 字段 Schema、上限、脱敏示例 | 实际运行值、真实路径/IP、secret 示例 |
| 浏览器 | stats 白名单字段 | API Key、Authorization、`.env`、原始 config.yaml、未脱敏命令 |

## Secret 禁止规则

以下内容不得进入 TCP 扩展对象、Go 内存快照、持久化 stats、日志、OpenAPI 示例或浏览器：

- API Key 或任何 provider key。
- Token secret、refresh token、session secret。
- Password。
- `Authorization` header 或 Bearer 值。
- `.env` 原始内容或整行。
- `config.yaml` 中的密钥原值或原始文件内容。

服务端不应依赖字段名黑名单作为唯一防线：所有对象使用白名单 Schema；对允许的自由文本字段仍需执行值扫描和替换。发现疑似 secret 时拒绝该扩展域或以 `[redacted]` 替换，并只记录安全错误码。

## 兼容规则

- 新客户端发送结构化 `hardware`、`docker`、`hermes`。
- 过渡期旧客户端可发送 `hardware_json`、`docker_json`、`hermes_json`；Go wire decoder 在内存中解析为结构化对象后执行同一验证。
- 若同一 update 同时包含结构化和旧字段，结构化字段优先；旧字段不参与合并。
- 原始旧字段绝不进入 NodeState、stats 或日志。
- 没有任何扩展字段的原生客户端仍可上报基础指标；服务端输出 `not_reported` 的空/stale 扩展对象。
- 扩展字段失败不拒绝基础 update，除非整个 TCP JSON 无法解析或超过 Go 全局请求上限。

## 关联文档

- 范围决策：[SCOPE_DECISIONS.md](SCOPE_DECISIONS.md)
- API 差异：[API_DIFF.md](API_DIFF.md)
- 配置来源：[CONFIG_DIFF.md](CONFIG_DIFF.md)
- Go 映射：[GO_IMPLEMENTATION_MAP.md](GO_IMPLEMENTATION_MAP.md)
- Fixture：[../../testdata/migration](../../testdata/migration)
