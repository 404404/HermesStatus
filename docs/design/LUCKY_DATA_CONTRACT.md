# Lucky 数据合同草案

## 目录

- [合同原则](#合同原则)
- [根对象](#根对象)
- [通用枚举](#通用枚举)
- [service](#service)
- [version](#version)
- [ip_resolution](#ip_resolution)
- [模块摘要](#模块摘要)
- [dynamic_dns.records](#dynamic_dnsrecords)
- [web_services.services](#web_servicesservices)
- [port_forwards.rules](#port_forwardsrules)
- [certificates.items](#certificatesitems)
- [错误对象](#错误对象)
- [时间与 stale](#时间与-stale)
- [版本比较](#版本比较)
- [示例](#示例)
- [禁止字段](#禁止字段)
- [关联文档](#关联文档)

## 合同原则

- `lucky` 与 `hardware`、`docker`、`hermes` 并列。
- JSON Schema 使用 Draft 2020-12，所有业务对象 `additionalProperties: false`。
- 空集合为 `[]`；未知数值和时间为 `null`；不以 `0` 或空字符串冒充未知。
- Client 只发送结构化 `lucky`；不新增 `lucky_json`。
- Lucky 域建议最大 512 KiB，完整 extension update 继续遵守现有 1 MiB 上限。
- 每个列表最多 128 项；超限时设置 `limit=128`、`truncated=true`，总数仍保留。
- 只允许本合同字段进入 Server、stats、OpenAPI 和 Browser。

## 根对象

| 字段 | 类型 | 必填 | null | 默认 | 限制 | 来源 |
| --- | --- | --- | --- | --- | --- | --- |
| `status` | enum string | 是 | 否 | `not_configured` | 见通用枚举 | 聚合计算 |
| `source` | enum string | 是 | 否 | `unavailable` | 见通用枚举 | collector |
| `service` | object | 是 | 否 | not_configured 对象 | 无额外字段 | systemd/API |
| `version` | object | 是 | 否 | unknown 对象 | 无额外字段 | Lucky/官方源 |
| `ip_resolution` | object | 是 | 否 | unknown 对象 | 无地址数组 | Lucky API |
| `dynamic_dns` | object | 是 | 否 | 空模块 | 最多 128 条 | Lucky API |
| `web_services` | object | 是 | 否 | 空模块 | 最多 128 条 | Lucky API |
| `port_forwards` | object | 是 | 否 | 空模块 | 最多 128 条 | Lucky API |
| `certificates` | object | 是 | 否 | 空模块 | 最多 128 条 | Lucky API |
| `collected_at` | RFC3339 string/null | 是 | 是 | null | 40 字符 | Client |
| `updated_at` | RFC3339 string/null | 是 | 是 | null | 40 字符 | 最近成功或部分成功采集 |
| `stale` | boolean | 是 | 否 | true | - | Server 重新计算 |
| `error` | object/null | 是 | 是 | null | 见错误对象 | collector/server |

`not_configured` 时仍输出完整对象结构，所有列表为 `[]`、时间为 null、stale 为 true，错误 code 为 `not_configured`。

## 通用枚举

| 枚举 | 允许值 |
| --- | --- |
| Lucky 总体状态 | `ok`, `degraded`, `error`, `not_configured`, `unavailable`, `stale` |
| 数据来源 | `api`, `local_api`, `config`, `cli`, `web_fallback`, `unavailable` |
| 模块状态 | `ok`, `degraded`, `error`, `not_configured`, `unavailable`, `unknown` |
| 服务状态 | `running`, `stopped`, `failed`, `activating`, `unknown`, `unavailable` |
| 记录状态 | `healthy`, `error`, `disabled`, `unknown` |
| 证书状态 | `valid`, `expiring`, `expired`, `not_yet_valid`, `invalid`, `unknown` |
| 协议 | `tcp`, `udp`, `http`, `https`, `http_https`, `other`, `unknown` |

## service

| 字段 | 类型 | 必填/null | 默认 | 限制/规则 |
| --- | --- | --- | --- | --- |
| `state` | enum string | 是/否 | `unknown` | 服务状态枚举 |
| `process_running` | boolean/null | 是/是 | null | 不能仅凭端口推导 true |
| `uptime_seconds` | integer/null | 是/是 | null | 0..9007199254740991 |
| `api_reachable` | boolean | 是/否 | false | 完整 API 语义检查 |
| `web_reachable` | boolean | 是/否 | false | 回环 HTTP 可达 |
| `updated_at` | RFC3339/null | 是/是 | null | 40 字符 |
| `stale` | boolean | 是/否 | true | 900 秒 |
| `error` | object/null | 是/是 | null | 安全错误对象 |

进程 PID 可以在 collector 内用于诊断，但不进入合同。

## version

| 字段 | 类型 | 必填/null | 默认 | 限制/规则 |
| --- | --- | --- | --- | --- |
| `current` | string/null | 是/是 | null | 64 字符，规范化显示值 |
| `latest` | string/null | 是/是 | null | 64 字符 |
| `update_available` | boolean/null | 是/是 | null | 仅可靠可比较时设置 |
| `build_time` | RFC3339/null | 是/是 | null | 40 字符 |
| `checked_at` | RFC3339/null | 是/是 | null | 最新版本最近检查时间 |
| `source` | enum string | 是/否 | `unavailable` | 数据来源枚举 |
| `stale` | boolean | 是/否 | true | 最新版本独立 freshness |
| `error` | object/null | 是/是 | null | 查询失败不令 Lucky 整体 error |

## ip_resolution

| 字段 | 类型 | 必填/null | 默认 | 限制/规则 |
| --- | --- | --- | --- | --- |
| `mode` | string/null | 是/是 | null | 64 字符，只允许归一化名称 |
| `ipv4_count` | integer/null | 是/是 | null | 0..100000 |
| `ipv6_count` | integer/null | 是/是 | null | 0..100000 |
| `resolved_ip_count` | integer/null | 是/是 | null | 等于可用 v4+v6 去重总数 |
| `effective_ip_count` | integer/null | 是/是 | null | Lucky 实际采用的去重总数 |
| `status` | enum string | 是/否 | `unknown` | 模块状态枚举 |
| `updated_at` | RFC3339/null | 是/是 | null | 40 字符 |
| `stale` | boolean | 是/否 | true | 900 秒 |
| `error` | object/null | 是/是 | null | 安全错误对象 |

完整 IPv4/IPv6 地址不得进入默认 wire 或 stats；未来如确有需求，必须通过新合同版本和显式脱敏开关评审。

## 模块摘要

`dynamic_dns`、`web_services` 和 `port_forwards` 共用以下计数语义；证书使用独立计数。

| 字段 | 类型 | 必填/null | 默认 | 限制/规则 |
| --- | --- | --- | --- | --- |
| `total` | integer/null | 是/是 | null | 未成功读取时为 null |
| `enabled` | integer/null | 是/是 | null | `<= total` |
| `disabled` | integer/null | 是/是 | null | `enabled + disabled = total`（可分类时） |
| `healthy` | integer/null | 是/是 | null | `<= total` |
| `error_count` | integer/null | 是/是 | null | 避免字段名与错误对象冲突 |
| `limit` | integer | 是/否 | 128 | 0..128 |
| `truncated` | boolean | 是/否 | false | 列表被裁剪时 true |
| 列表字段 | array | 是/否 | `[]` | 最多 128 |
| `status` | enum string | 是/否 | `unknown` | 模块状态 |
| `updated_at` | RFC3339/null | 是/是 | null | 40 字符 |
| `stale` | boolean | 是/否 | true | 900 秒 |
| `error` | object/null | 是/是 | null | 模块级错误 |

计数必须来自完整列表或 Lucky 明确提供的汇总；不能用截断后的数组长度冒充 total。

## dynamic_dns.records

| 字段 | 类型 | 必填/null | 默认 | 最大长度/规则 |
| --- | --- | --- | --- | --- |
| `id` | string | 是/否 | 无 | 128；稳定脱敏标识，不使用 secret |
| `display_name` | string | 是/否 | `-` | 128；业务名或脱敏名称，不默认输出完整域名 |
| `provider` | string/null | 是/是 | null | 64；provider 名称，不含账号 |
| `address_method` | string/null | 是/是 | null | 256；地址获取方式，不包含解析出的 IP |
| `local_record_change_status` | string/null | 是/是 | null | 32；规范化本地记录变化状态 |
| `updated_records` | integer/null | 是/是 | null | 0..9007199254740991，且不大于 total_records |
| `total_records` | integer/null | 是/是 | null | 0..9007199254740991 |
| `enabled` | boolean | 是/否 | false | - |
| `status` | enum string | 是/否 | `unknown` | 记录状态 |
| `record_type` | string/null | 是/是 | null | 16，例如 `A`/`AAAA` |
| `last_update_at` | RFC3339/null | 是/是 | null | 40；Lucky `LastSyncTime` 的归一化值 |
| `next_sync_at` | RFC3339/null | 是/是 | null | 40；Lucky `NextSyncTime` 的归一化值 |
| `last_success_at` | RFC3339/null | 是/是 | null | 40 |
| `error` | object/null | 是/是 | null | 不含上游响应 |

## web_services.services

| 字段 | 类型 | 必填/null | 默认 | 最大长度/规则 |
| --- | --- | --- | --- | --- |
| `id` | string | 是/否 | 无 | 128；稳定脱敏标识 |
| `display_name` | string | 是/否 | `-` | 128 |
| `enabled` | boolean | 是/否 | false | - |
| `status` | enum string | 是/否 | `unknown` | 记录状态 |
| `protocol` | enum string | 是/否 | `unknown` | 协议枚举 |
| `listen_port` | integer/null | 是/是 | null | 1..65535 |
| `upstream_type` | string/null | 是/是 | null | 64；类型，不是地址 |
| `tls_enabled` | boolean/null | 是/是 | null | - |
| `certificate_ref` | string/null | 是/是 | null | 128；脱敏引用 |
| `connection_count` | integer/null | 是/是 | null | 0..9007199254740991 |
| `enabled_subrules` | integer/null | 是/是 | null | 0..9007199254740991，且不大于 total_subrules |
| `total_subrules` | integer/null | 是/是 | null | 0..9007199254740991 |
| `error` | object/null | 是/是 | null | 安全错误对象 |

## port_forwards.rules

| 字段 | 类型 | 必填/null | 默认 | 最大长度/规则 |
| --- | --- | --- | --- | --- |
| `id` | string | 是/否 | 无 | 128；稳定脱敏标识 |
| `display_name` | string | 是/否 | `-` | 128 |
| `enabled` | boolean | 是/否 | false | - |
| `status` | enum string | 是/否 | `unknown` | 记录状态 |
| `protocol` | enum string | 是/否 | `unknown` | 协议枚举 |
| `listen_port` | integer/null | 是/是 | null | 1..65535 |
| `target_type` | string/null | 是/是 | null | 64；类型，不是目标地址 |
| `connection_count` | integer/null | 是/是 | null | 0..9007199254740991 |
| `error` | object/null | 是/是 | null | 安全错误对象 |

## certificates.items

证书模块计数为 `total`、`valid`、`expiring`、`expired`、`not_yet_valid`、`invalid`、`unknown`，均为 integer/null。另含 `warning_days`（integer，默认 30，1..365）、`limit`、`truncated`、`items`、`status`、`updated_at`、`stale` 和 `error`。

| 字段 | 类型 | 必填/null | 默认 | 最大长度/规则 |
| --- | --- | --- | --- | --- |
| `id` | string | 是/否 | 无 | 128；稳定脱敏标识 |
| `display_name` | string | 是/否 | `-` | 128；业务名或脱敏标识 |
| `san_count` | integer/null | 是/是 | null | 0..10000；不输出 SAN 值 |
| `issuer` | string/null | 是/是 | null | 128；组织显示名，必要时脱敏 |
| `source` | string/null | 是/是 | null | 64；如 `acme`/`uploaded`/`unknown` |
| `not_before` | RFC3339/null | 是/是 | null | 40 |
| `not_after` | RFC3339/null | 是/是 | null | 40 |
| `remaining_days` | integer/null | 是/是 | null | 向下取整，可为负数 |
| `status` | enum string | 是/否 | `unknown` | 证书状态枚举 |
| `auto_renew` | boolean/null | 是/是 | null | - |
| `last_renew_at` | RFC3339/null | 是/是 | null | 40 |
| `next_renew_at` | RFC3339/null | 是/是 | null | 40 |
| `error` | object/null | 是/是 | null | 安全错误对象 |

证书状态规则：

1. 解析失败或 Lucky 明确报告证书错误：`invalid`。
2. 缺少足够时间数据且无明确错误：`unknown`。
3. 当前时间早于 `not_before`：`not_yet_valid`。
4. 当前时间晚于 `not_after`：`expired`。
5. `0 <= remaining_days <= warning_days`：`expiring`。
6. 其余有效期内证书：`valid`。

所有输入时间先归一化为 UTC；Browser 仅负责本地化显示，不重新定义核心状态。

## 错误对象

沿用 HermesStatus `ExtensionError` 形状：

| 字段 | 类型 | null | 限制 |
| --- | --- | --- | --- |
| `code` | string | 否 | 64；小写 snake_case allowlist |
| `message` | string | 否 | 256；固定脱敏摘要 |
| `source` | string | 否 | 64；固定 adapter/module 标签 |
| `retryable` | boolean | 否 | - |
| `http_status` | integer/null | 是 | 100..599；Lucky `ret` 另映射为 code，不原样输出 msg |

建议 code：`not_configured`、`connection_refused`、`timeout`、`unauthorized`、`forbidden`、`invalid_response`、`schema_mismatch`、`response_too_large`、`version_check_failed`、`certificate_parse_failed`、`clock_skew`、`internal_error`。

## 时间与 stale

- Client 采集间隔默认 600 秒。
- Lucky 根域、service、IP、DDNS、Web、转发和证书 stale 阈值为 900 秒。
- `updated_at=null` 时 stale=true。
- 采集时间超过阈值时 stale=true。
- 时间比 Server 未来超过 300 秒时 stale=true，并附安全 `clock_skew` error。
- `received_at` 不参与 stale；stats 每次序列化不得改写 `updated_at`。
- 最新版本缓存 TTL 默认 21600 秒，超过 86400 秒未成功检查时 version.stale=true。
- last-good 保留原 `updated_at`/`checked_at`，失败不能伪造新鲜时间。

## 版本比较

- 去除显示前缀 `v` 后按 SemVer 比较。
- 支持 prerelease 和 build metadata；build metadata 不影响优先级。
- 无法解析任一版本时 `update_available=null` 并设置版本子模块错误。
- prerelease 不应自动覆盖同主版本稳定版；比较遵循 SemVer precedence。
- 不能使用普通字符串不等判断更新。

## 示例

以下为脱敏、非生产示例：

```json
{
  "status": "degraded",
  "source": "local_api",
  "service": {
    "state": "running",
    "process_running": true,
    "uptime_seconds": 7200,
    "api_reachable": true,
    "web_reachable": true,
    "updated_at": "2030-01-01T00:00:00Z",
    "stale": false,
    "error": null
  },
  "version": {
    "current": "2.27.2",
    "latest": null,
    "update_available": null,
    "build_time": null,
    "checked_at": null,
    "source": "local_api",
    "stale": true,
    "error": {
      "code": "version_check_failed",
      "message": "Latest version is unavailable",
      "source": "lucky_version",
      "retryable": true,
      "http_status": null
    }
  },
  "ip_resolution": {
    "mode": "network_interface",
    "ipv4_count": 1,
    "ipv6_count": 1,
    "resolved_ip_count": 2,
    "effective_ip_count": 2,
    "status": "ok",
    "updated_at": "2030-01-01T00:00:00Z",
    "stale": false,
    "error": null
  },
  "dynamic_dns": {
    "total": 1,
    "enabled": 1,
    "disabled": 0,
    "healthy": 1,
    "error_count": 0,
    "limit": 128,
    "truncated": false,
    "records": [],
    "status": "ok",
    "updated_at": "2030-01-01T00:00:00Z",
    "stale": false,
    "error": null
  },
  "web_services": {
    "total": 0,
    "enabled": 0,
    "disabled": 0,
    "healthy": 0,
    "error_count": 0,
    "limit": 128,
    "truncated": false,
    "services": [],
    "status": "ok",
    "updated_at": "2030-01-01T00:00:00Z",
    "stale": false,
    "error": null
  },
  "port_forwards": {
    "total": 0,
    "enabled": 0,
    "disabled": 0,
    "healthy": 0,
    "error_count": 0,
    "limit": 128,
    "truncated": false,
    "rules": [],
    "status": "ok",
    "updated_at": "2030-01-01T00:00:00Z",
    "stale": false,
    "error": null
  },
  "certificates": {
    "total": 0,
    "valid": 0,
    "expiring": 0,
    "expired": 0,
    "not_yet_valid": 0,
    "invalid": 0,
    "unknown": 0,
    "warning_days": 30,
    "limit": 128,
    "truncated": false,
    "items": [],
    "status": "ok",
    "updated_at": "2030-01-01T00:00:00Z",
    "stale": false,
    "error": null
  },
  "collected_at": "2030-01-01T00:00:00Z",
  "updated_at": "2030-01-01T00:00:00Z",
  "stale": false,
  "error": null
}
```

## 禁止字段

以下字段或内容不得以任何命名变体出现：API Key、Token 值、Cookie、password、Authorization、private key、PEM/PFX/P12 内容或密码、ACME account key、原始 config、raw response、command、完整 IP、完整域名、上游地址、转发目标、认证 Header、查询参数 secret。

## 关联文档

- [总体设计](LUCKY_MONITORING.md)
- [API 清单](LUCKY_API_INVENTORY.md)
- [安全边界](LUCKY_SECURITY.md)
- [部署与实施计划](LUCKY_DEPLOYMENT_PLAN.md)
