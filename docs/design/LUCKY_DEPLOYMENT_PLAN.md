# Lucky Monitoring 实施与部署计划

## 目录

- [原则](#原则)
- [配置草案](#配置草案)
- [计划文件](#计划文件)
- [阶段 E：Client adapter](#阶段-eclient-adapter)
- [阶段 F：Go 数据管线](#阶段-fgo-数据管线)
- [阶段 G：前端](#阶段-g前端)
- [阶段 H：测试](#阶段-h测试)
- [阶段 I：候选部署](#阶段-i候选部署)
- [阶段 J：PR 与 CI](#阶段-jpr-与-ci)
- [阶段 K：最终部署](#阶段-k最终部署)
- [部署步骤](#部署步骤)
- [验证清单](#验证清单)
- [回滚](#回滚)
- [风险和阻断项](#风险和阻断项)
- [关联文档](#关联文档)

## 原则

- 每个阶段独立 PR，保持 Client、Server、UI 和部署边界可审查。
- CI 全程使用 fixture/mock，不访问真实 Lucky、内网或生产凭据。
- 生产环境的 Lucky 不修改、不重启、不更新。
- 默认关闭 Lucky 采集；配置齐全后显式启用。
- 最终环境使用同宿主机 `http://127.0.0.1:16601`，不配置远程 Lucky 地址。
- 任何候选部署都必须先备份 HermesStatus 配置和镜像标识，并保持可回滚。

## 配置草案

配置名基于已确认接口和同机部署边界，实际加入 Compose 前需经过实现 PR 评审。

| 配置 | 默认 | 用途 |
| --- | --- | --- |
| `LUCKY_ENABLED` | `false` | 显式启用采集 |
| `LUCKY_BASE_URL` | `http://127.0.0.1:16601` | 仅回环控制面 |
| `LUCKY_AUTH_MODE` | `open_token` | 首版唯一候选认证模式 |
| `LUCKY_TOKEN_FILE` | `/run/secrets/lucky-open-token` | 容器内只读凭据文件 |
| `LUCKY_TIMEOUT_SECONDS` | `5` | 总读取超时 |
| `LUCKY_INTERVAL` | `600` | 完整采集周期 |
| `LUCKY_VERSION_CHECK_TTL` | `21600` | 最新版本缓存 TTL |
| `LUCKY_CERT_WARNING_DAYS` | `30` | 证书预警阈值 |
| `LUCKY_VERIFY_TLS` | `true` | HTTPS 时验证证书；回环 HTTP 不适用 |

不提供任意接口路径、任意 Header、关闭重定向限制或暴露完整地址的配置开关。生产 Token 不进入仓库、`.env` 示例值、Compose 输出报告或部署日志。

## 计划文件

### 新增

- `clients/lucky_collector.py`
- `clients/test_lucky_collector.py`
- `testdata/lucky/` 下的正常、空、降级、超限和 secret fixture
- `docs/migration/schema/lucky-agent-extension.schema.json`（或在现有扩展 Schema 中引用独立定义）
- Lucky 前后端针对性测试文件，名称按现有目录约定确定

### 修改

- `clients/host_collector.py`：独立缓存和 structured payload 接入
- `clients/client-linux.py`、`clients/client-psutil.py`：仅在现有 collector 初始化边界需要时修改
- `clients/entrypoint.sh`：仅在需要独立版本缓存任务时修改；优先不新增进程
- `server/extension_model.go`
- `server/extension_validation.go`
- `server/extension_pipeline.go`
- `server/app.go`
- `server/extension_openapi.go`
- 对应 Go 测试
- `docs/migration/STATS_CONTRACT.md` 和两个 extension Schema
- `testdata/migration/` extension fixture
- `web/index.html`
- `web/css/app.css`
- `web/js/app.js`
- `web/js/app.test.js`
- `scripts/check_release_boundaries.py`
- `docker-compose-client.yml`
- `hermesstatus` 客户端配置示例/部署文档（不含真实值）

### 明确不修改

- `docker-compose-server.yml` 的 Lucky 凭据和挂载
- `server/config.json` 节点配置 Schema
- Lucky 自身配置、服务文件或模块状态
- Legacy `hardware_json`、`docker_json`、`hermes_json` 决策
- Docker command 字段

## 阶段 E：Client adapter

1. 以 mock 响应先实现 `LuckyClient` 的固定 GET allowlist、Header 认证、超时、响应上限和 `ret` 语义。
2. 实现模块 normalizer，不保留原始响应。
3. 实现 service/systemd 探测与 API 状态组合。
4. 实现版本规范化、SemVer 比较和 6 小时缓存。
5. 实现证书 UTC 时间和六状态计算。
6. 接入 `HostCollector` 独立 600 秒缓存；异常不得传播到主循环。
7. 不加入 `lucky_json`，不在日志打印请求/响应对象。

门禁：Python 单测和 secret 测试通过，Lucky disabled 时现有 payload 行为不变。

## 阶段 F：Go 数据管线

1. 增加严格 Lucky 类型、枚举、上限和 not_configured/not_reported 构造器。
2. TCP update 只接受 structured `lucky`，单域验证失败安全降级。
3. NodeState 保存验证后的 Lucky，不保存 raw 数据。
4. Snapshot 副本计算 900 秒 stale 和 300 秒 future skew。
5. stats persistence 写出 Lucky，但服务重启不恢复为新鲜实时状态。
6. `/json/stats.json` 和 OpenAPI 增加 allowlist Lucky Schema。
7. 不改变原生和已有三域行为。

门禁：Go test/race/vet/build 通过，1 MiB update 边界不被扩大。

## 阶段 G：前端

1. 增加主页 Lucky 摘要。
2. 新增同级 `#lucky` 页面和五个区块。
3. 扩展 `normalizeNodeView`，所有数组和对象使用安全默认值。
4. 复用 `currentStats`、一个 10 分钟 timer 和全局手动刷新。
5. 证书状态来自合同，Browser 只做时区格式化。
6. 无控制按钮、原始 JSON、Token、完整域名/IP/目标地址。
7. 桌面和移动端执行截图与布局检查。

门禁：Hash 恢复、标签切换零请求、手动刷新单请求、自动刷新单 timer 测试通过。

## 阶段 H：测试

### contracts

- 正常、空、not_configured、unavailable、degraded、stale、超限和 secret fixture。
- Schema Draft 2020-12、`additionalProperties:false`、数组和字符串上限。

### python

- API 200/401/403/404/500、Lucky `ret` 失败、超时、拒绝连接、非 JSON、超大响应。
- 四个业务模块正常/部分失败；版本前缀/prerelease/cache；六种证书状态。
- Header/Token/原始响应不进入日志和结果。

### go

- Lucky structured payload、缺失、各状态、非法枚举/时间/长度/数组/secret。
- Lucky 错误不影响原生和 hardware/docker/hermes。
- stale、clock skew、持久化和重启 freshness。

### frontend

- 主页摘要、`#lucky`、五区块、空/降级/stale/证书状态、移动/桌面。
- 只有一个 timer；Browser 只请求 stats；无 Lucky API/WS/SSE 和控制按钮。

### compose/images/security

- Client 配置和 Secret 挂载只读；Server 无 Lucky 凭据。
- 镜像中不含 Token；release boundary 不弱化现有七项检查。
- 静态扫描禁止 Lucky 直连、管理 Header、write path 和 raw response 字段。

## 阶段 I：候选部署

部署必须等待用户确认环境和认证门禁。顺序：

1. 只读核对 Lucky 版本、回环可达和现有 HermesStatus 健康。
2. 准备宿主机专用 Token 文件，不输出值。
3. 备份当前 HermesStatus Compose/config 和镜像标识。
4. 在远端按候选 Commit SHA 构建 Server/Client 镜像。
5. 停止旧 HermesStatus 容器，使用原端口和数据目录启动候选容器。
6. 检查容器 healthy、restart count=0、stats 包含 Lucky 且无 secret。
7. 验证 Lucky 页面和现有主页/Docker/Hermes 功能。
8. 观察 Lucky 日志/审计的脱敏摘要，确认仅调用允许 GET。
9. 由用户人工确认效果后才能 Push/PR。

不重启、不更新、不修改 Lucky。

## 阶段 J：PR 与 CI

- 每个实现阶段从最新 `origin/2.0` 建分支。
- 先本地/候选部署验收，再按用户门禁 Commit、Push、Draft PR。
- PR 目标 `2.0`，七个 Required Checks 必须保持：contracts、go、python、frontend、compose、images、security。
- CI 不访问 `localhost:16601` 或任何真实 Lucky；全部使用 mock/fixture。
- 不自动 Merge、Tag 或创建 GitHub Release。

## 阶段 K：最终部署

合并后使用 merge SHA 重新构建不可变版本镜像，核对 OCI provenance，再以相同端口、数据目录、Secret 文件和 Runtime Hardening 配置部署。候选镜像不能直接冒充最终 merge SHA 镜像。

## 部署步骤

建议最终 Compose 只对 Client 增加：

- `LUCKY_*` 非敏感环境变量；
- 单个 Token 文件只读挂载；
- 不增加端口、network、capability、device 或 privileged 权限。

部署前后均保存以下非敏感证据：Commit SHA、镜像 ID/标签、容器健康、restart count、stats Schema 验证、允许路径调用计数和 UI 截图。不得保存 Token、原始响应或 Lucky 配置。

## 验证清单

- Lucky service/API/Web 状态符合实际。
- 当前版本正确；最新版本失败不会破坏其他模块。
- IP 只显示数量，无地址。
- DDNS、Web、转发、证书计数和状态与 Lucky 页面人工抽样一致。
- 六种证书状态及 30 天阈值正确。
- 600 秒采集、900 秒 stale、6 小时版本 TTL 正确。
- Browser 切页不新增请求，10 分钟刷新仍只有一个 timer。
- `/json/stats.json` 为 `no-store`，无 raw/secret/完整地址。
- Lucky 不可达、认证失败、单模块失败均只影响 Lucky。
- Server/Client healthy，restart count=0，已有三域无回归。

## 回滚

1. 停止候选 HermesStatus 容器。
2. 恢复上一已验证镜像标签和 Compose/config 备份。
3. 保留同一 Server 数据目录，确认 stats persistence 正常。
4. 如仅 Lucky 采集异常，可先设置 `LUCKY_ENABLED=false` 并重启 Client，不改 Server/Lucky。
5. 检查旧 UI/已有三域、端口和容器健康。
6. 不删除 Lucky 配置、不轮换或打印 Token、不重启 Lucky。

## 风险和阻断项

| 风险 | 状态 | 处理 |
| --- | --- | --- |
| OpenToken 可能是全权限 | 阻断生产凭据部署 | 只读能力确认或用户接受剩余风险 |
| 内部 API 无稳定 Schema | 可控 | adapter/fixture/版本兼容测试 |
| 已认证响应字段未完成脱敏采样 | 阻断真实 normalizer 完成 | 只读采样，仅记录字段结构 |
| 最新版本源未固化 | 非整体阻断 | `latest=null`，版本子模块 degraded |
| 模块响应可能含敏感配置 | 高风险 | 字段 allowlist，不保存 raw response |
| Client 已有较高宿主机权限 | 既有风险 | Lucky 不扩大权限；后续独立收敛 |

## 关联文档

- [总体设计](LUCKY_MONITORING.md)
- [API 清单](LUCKY_API_INVENTORY.md)
- [数据合同](LUCKY_DATA_CONTRACT.md)
- [安全边界](LUCKY_SECURITY.md)
- [现有部署文档](../operations/DEPLOYMENT.md)
- [现有回滚文档](../operations/ROLLBACK.md)
