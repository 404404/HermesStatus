# Lucky API 清单

## 目录

- [范围与证据](#范围与证据)
- [认证与通用响应](#认证与通用响应)
- [选定只读接口](#选定只读接口)
- [其他已发现只读接口](#其他已发现只读接口)
- [写入或控制接口](#写入或控制接口)
- [WebSocket 与 SSE](#websocket-与-sse)
- [版本来源](#版本来源)
- [字段映射决策](#字段映射决策)
- [兼容风险](#兼容风险)
- [未确认响应结构](#未确认响应结构)
- [关联文档](#关联文档)

## 范围与证据

本清单来自 Lucky 官方文档、当前安装版本的公开静态前端和只读 HTTP 探测。没有调用任何写接口，也没有读取或记录真实认证值。

| 等级 | 含义 |
| --- | --- |
| A | Lucky 官方文档明确描述的稳定只读接口或能力 |
| B | 当前 Lucky Web 前端使用的内部只读接口 |
| C | 本地模块状态或配置文件，只作为 API 失败兜底 |
| D | systemd、进程、监听或 CLI 推导 |
| E | HTML/DOM 抓取，不作为生产默认来源 |

接口路径和 Method 可由当前静态前端确认；内部响应 Schema 没有官方契约，必须通过 fixture 固化 adapter 边界。

## 认证与通用响应

| 项目 | 结论 |
| --- | --- |
| 公共接口 | `GET /version` 无认证可访问 |
| Web 管理认证 | Header `Lucky-Admin-Token`，值来自 Web 登录态 |
| OpenToken | 官方说明用于第三方 API 调用；Header 名或查询参数名为 `openToken` |
| Cookie | 未发现模块 API 必须依赖 Cookie；生产设计禁止复用浏览器 Cookie |
| HTTP 状态 | 未认证请求可返回 HTTP 200，同时 JSON `ret` 为失败值 |
| 成功判定 | HTTP 2xx、JSON object、`ret` 成功语义和目标字段校验必须同时通过 |
| 只读授权 | 未发现 OpenToken 的只读 scope、端点 allowlist 或方法限制 |

查询参数方式容易进入访问日志和代理日志，生产实现只允许 Header，不允许 `?openToken=...`。

## 选定只读接口

| 业务 | Path | Method | 认证 | 等级 | 只读 | 选用结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 当前版本 | `/version` | GET | 无 | A/B | 是 | 主来源 |
| 运行信息 | `/api/info` | GET | Token | B | 是 | 受控补充来源 |
| API 状态 | `/api/status` | GET | Token | B | 是 | 仅用于健康摘要，响应待固化 |
| 模块列表 | `/api/modules/list` | GET | Token | B | 是 | 判断模块是否启用 |
| 网络接口 | `/api/netinterfaces` | GET | Token | B | 是 | 仅归一化为 IP 数量和解析方式 |
| DDNS 列表 | `/api/ddnstasklist` | GET | Token | B | 是 | 主列表来源 |
| DDNS 详情 | `/api/ddns/task/{id}` | GET | Token | B | 是 | 只在列表不足时调用 |
| Web 服务列表 | `/api/webservice/rules` | GET | Token | B | 是 | 主列表来源 |
| Web 服务详情 | `/api/webservice/rule/{id}` | GET | Token | B | 是 | 只在列表不足时调用 |
| 端口转发列表 | `/api/portforwards` | GET | Token | B | 是 | 主列表来源 |
| 端口转发详情 | `/api/portforward/{id}` | GET | Token | B | 是 | 只在列表不足时调用 |
| SSL 列表 | `/api/ssl` | GET | Token | B | 是 | 主证书来源 |
| SSL 详情 | `/api/ssl/{id}` | GET | Token | B | 是 | 仅提取公开证书元数据 |
| SSL 设置 | `/api/ssl/setting` | GET | Token | B | 是 | 仅在需要 warning/renew 元数据时使用 |

首版不依赖 `*_lite` 接口，因为它们的字段裁剪规则没有文档；如果列表接口响应过大，可在 fixture 验证后替换。

## 其他已发现只读接口

| Path | Method | 备注 |
| --- | --- | --- |
| `/api/logs` | GET | 原始日志不进入监控合同 |
| `/api/baseconfigure` | GET | 可能包含敏感配置，不选用 |
| `/api/oauth/status` | GET | 与 Lucky Monitoring 无关 |
| `/api/oauth/userinfo` | GET | 与 Lucky Monitoring 无关 |
| `/api/ddns/odhcpdclients` | GET | 特定平台数据，不作为通用来源 |
| `/api/ddns/configure` | GET | 可能包含 provider 配置，不选用 |
| `/api/ddns/logs` | GET | 原始日志不选用 |
| `/api/ddns/lastlogs` | GET | 原始日志不选用 |
| `/api/portforwards_lite` | GET | 候选列表来源，Schema 待验证 |
| `/api/portforward/{id}/logs` | GET | 原始日志不选用 |
| `/api/portforward/{id}/lastlogs` | GET | 原始日志不选用 |
| `/api/webservice/rules_lite` | GET | 候选列表来源，Schema 待验证 |
| `/api/webservice/modulesettings/frontend` | GET | 只含前端设置时才可候选，首版不使用 |
| `/api/webservice/logs` | GET | 原始日志不选用 |
| `/api/webservice/lastlogs` | GET | 原始日志不选用 |
| `/api/ssl/logs` | GET | 原始日志不选用 |
| `/api/ssl/lastlogs` | GET | 原始日志不选用 |

“接口是 GET”不自动等同于安全可用。返回原始配置、日志、身份信息或网络目标的 GET 接口仍不进入采集 allowlist。

## 写入或控制接口

以下接口只用于边界识别，HermesStatus 不得调用。

| Path | Method | 分类 |
| --- | --- | --- |
| `/api/login`、`/api/oauth/login` | POST | 登录 |
| `/api/logout` | PUT | 会话变更 |
| `/api/baseconfigure` | PUT | 全局配置写入 |
| `/api/lucky/service` | PUT | 服务控制 |
| `/api/reboot_program` | GET | 语义为重启，虽为 GET 仍是写操作 |
| `/api/update/comfire` | PUT | 更新控制 |
| `/api/update/cancel` | GET | 语义为取消更新，虽为 GET 仍是写操作 |
| `/api/ddns` | POST/PUT/DELETE | DDNS 规则写入 |
| `/api/ddns/enable` | GET | 语义为启停，禁止调用 |
| `/api/ddns/manualSync/{id}` | GET | 语义为立即同步，禁止调用 |
| `/api/ddns/recordOrderadjustment/{id}` | PUT | 排序写入 |
| `/api/ddns/taskorderadjustment` | PUT | 排序写入 |
| `/api/ddns/webhooktest` | POST | 外部请求测试 |
| `/api/ddns/getipfromcmdtest` | GET | 可执行命令测试，禁止调用 |
| `/api/portforward` | POST/PUT/DELETE | 规则写入 |
| `/api/portforward/enable` | GET | 语义为启停，禁止调用 |
| `/api/portforward/configure` | PUT | 配置写入 |
| `/api/portforward/ruleorderadjustment` | PUT | 排序写入 |
| `/api/webservice/rules` | POST | 新增规则 |
| `/api/webservice/rule/{id}` | PUT/DELETE | 修改或删除规则 |
| `/api/webservice/modulesettings` | PUT | 模块设置写入 |
| `/api/webservice/tipread` | PUT | 状态写入 |
| `/api/webservice/cgi` | POST/PUT/DELETE | CGI 配置写入 |
| `/api/webservice/groups` | POST/PUT/DELETE | 分组写入 |
| `/api/ssl` | POST/PUT/DELETE | 证书配置写入 |
| `/api/ssl/{id}` | PUT | 证书启停 |
| `/api/ssl/flush` | PUT | 刷新/续签操作 |
| `/api/ssl/manualsync/{id}` | GET | 语义为同步，禁止调用 |
| `/api/ssl/syncclients` | GET | 可能触发同步，禁止调用 |
| `/api/ssl/setting` | PUT | SSL 设置写入 |
| `/api/ssl/sslorderadjustment` | PUT | 排序写入 |

所有未列入“选定只读接口”的路径默认拒绝。adapter 不提供通用 request(path, method) 给业务层调用。

## WebSocket 与 SSE

- Lucky 状态页包含 WebSocket 状态流，但首版不使用；10 分钟摘要不需要常驻连接。
- Web 终端和 SFTP WebSocket 会携带管理 Token，明确禁止使用。
- 静态前端中未发现 SSE/EventSource。
- HermesStatus Browser 不连接任何 Lucky WebSocket。

## 版本来源

### 当前版本

`GET /version` 已确认返回 object，并包含：

| 字段 | 类型 | 使用方式 |
| --- | --- | --- |
| `version` | string | 规范化后写入 `current` |
| `buildTime` | string | 解析成功后转 RFC3339 UTC，否则 null |
| `ret` | number | 判断 Lucky 语义成功 |

### 最新版本

当前 Web 前端从 Lucky 下发的 `staticHost`、`appinfourl` 和版本元数据构造官方信息请求。该机制说明最新版本并非 `/version` 返回，但稳定 URL 和响应 Schema 尚未形成公开合同。

实施规则：

1. 优先使用 Lucky 后端已经取得并返回的官方版本信息；
2. 其次使用确认后的官方发布源；
3. 设置至少 6 小时 TTL，不随每次 stats 刷新访问公网；
4. 失败只令 version 子模块降级；
5. 只有 SemVer 可比较时才设置 `update_available`；否则为 null。

## 字段映射决策

| 业务字段 | 候选接口 | Method | 认证 | 只读 | 稳定性 | Secret 风险 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| service/API 状态 | `/api/status` + systemd | GET/本地 | Token/无 | 是 | B/D | 低 | 组合使用 |
| 当前版本 | `/version` | GET | 无 | 是 | A/B | 低 | 使用 |
| 最新版本 | 官方版本信息源 | GET | 无 | 是 | 未确认 | 低 | 长 TTL，未确认则 null |
| 解析方式/数量 | `/api/netinterfaces` + DDNS | GET | Token | 是 | B | 高，含地址 | 只保留枚举和计数 |
| DDNS 摘要 | `/api/ddnstasklist` | GET | Token | 是 | B | 高，可能含域名/provider 配置 | allowlist 归一化 |
| Web 服务摘要 | `/api/webservice/rules` | GET | Token | 是 | B | 高，可能含上游/Header | allowlist 归一化 |
| 端口转发摘要 | `/api/portforwards` | GET | Token | 是 | B | 高，可能含目标地址 | allowlist 归一化 |
| 证书摘要 | `/api/ssl` | GET | Token | 是 | B | 高，可能含证书配置 | 只保留名称、时间、状态、计数 |

## 兼容风险

- 所有 `/api/...` 选定模块接口均属于 Web 内部 API，Lucky 升级可能修改路径、字段、`ret` 语义或认证。
- adapter 必须固定兼容版本范围，严格校验顶层类型和 allowlist 字段。
- 未知字段不能透传，但上游新增字段本身不应导致失败；只对被读取字段做类型校验。
- 已知字段缺失或类型变化返回 `schema_mismatch`，只降级对应模块。
- 响应体上限、超时、同源重定向和 JSON Content-Type 必须在请求层统一执行。
- 每次 Lucky 升级先运行脱敏 fixture/候选环境兼容测试，再升级正式实例。

## 未确认响应结构

由于浏览器登录态在摸排时不可用，以下内容没有使用真实认证响应确认：

- `/api/status`、`/api/info` 和模块列表的完整字段；
- DDNS、Web 服务、端口转发、证书的列表容器字段名；
- 记录级健康、最后成功时间和错误字段；
- 证书自动续签、上次/下次续签字段；
- 最新版本官方响应 Schema。

这些字段必须在进入真实 adapter 前以脱敏、只读的响应结构清单补齐。不得把猜测字段写成已确认合同。

## 关联文档

- [总体设计](LUCKY_MONITORING.md)
- [数据合同](LUCKY_DATA_CONTRACT.md)
- [安全边界](LUCKY_SECURITY.md)
- [部署与实施计划](LUCKY_DEPLOYMENT_PLAN.md)

