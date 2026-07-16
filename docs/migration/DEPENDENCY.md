# HermesStatus 依赖清单

## 目录

- [依赖结论](#依赖结论)
- [APT 与系统构建依赖](#apt-与系统构建依赖)
- [Python 与 APK/PIP](#python-与-apkpip)
- [Go Modules](#go-modules)
- [NPM 与前端](#npm-与前端)
- [Docker 依赖](#docker-依赖)
- [Git Submodule 与内嵌代码](#git-submodule-与内嵌代码)
- [迁移后保留与删除](#迁移后保留与删除)
- [关联文档](#关联文档)

## 依赖结论

HermesStatus 1.0 没有 pip requirements、npm package 或 git submodule。客户端 Python 依赖由 Alpine APK 安装；服务端 C++ 构建和运行依赖将在迁移到 Go 2.0 后大部分删除。SMART、YAML、psutil、Docker Engine 与 Hermes CLI/API 仍是业务采集依赖。

## APT 与系统构建依赖

| 1.0 包 | 使用位置 | 用途 | Go 迁移后 |
| --- | --- | --- | --- |
| `gcc`, `g++`, `make` | `Dockerfile.server`, CI | 编译 C/C++ `sergate` | 删除 |
| `libcurl4-openssl-dev` | builder/CI | C++ libcurl 链接 | 删除 |
| `libcurl4`, `libstdc++6` | server runtime | C++ 运行库 | 删除 |
| `nginx-light` | server runtime | 静态文件和 API 反代 | 删除；Go HTTP 直接提供 |
| `python3` | server runtime | `manage_api.py`、healthcheck | 服务端删除；客户端仍需 |
| `openssl` | server runtime | 原生证书处理/运维 | Go `crypto/tls` 后删除运行依赖 |
| `ca-certificates`, `tzdata` | server runtime | TLS CA 与时区 | 保留 |
| `build-essential`/发行版编译工具 | `status.sh` | 非容器 C++ 安装 | 删除，替换为 Go build 需求 |

## Python 与 APK/PIP

| 包/模块 | 安装方式 | 使用者 | 用途 | 迁移后 |
| --- | --- | --- | --- | --- |
| `python3` | Alpine APK | 两个 client、exporter、summary | 采集运行时 | 第一阶段保留 |
| `py3-psutil` | Alpine APK | `client-psutil.py` | CPU/内存/磁盘/进程/网络 | 保留 |
| `py3-yaml` | Alpine APK | `hermes_config_summary.py` | 完整解析 Profile YAML | 保留；不要依赖简化 parser 作为主路径 |
| `iproute2` | Alpine APK | 原生 client 工具链 | 网络信息 | 保留至客户端依赖审计完成 |
| `procps` | Alpine APK | 原生 client/进程信息 | 主机指标 | 保留至客户端依赖审计完成 |
| `smartmontools` | Alpine APK | SMART 采集 | `smartctl -x`/JSON | 保留，HS-006 至 HS-008 |
| `util-linux` | Alpine APK | exporter | `nsenter` 宿主机执行 Hermes CLI | 首阶段保留；移除 host PID 路径后删除 |
| Python stdlib `http.client` | 内置 | exporter | Hermes HTTP API | 保留，无额外包 |
| Python stdlib Unix socket | 内置 | client | Docker Engine API | 保留，无额外包 |

仓库没有 `requirements.txt`、Pipfile 或 Poetry lock。当前 Python 版本/包版本由 Alpine 标签决定，迁移时应锁定并测试兼容版本。

## Go Modules

2.0 服务端直接依赖：

| 模块 | 版本 | 用途 | HermesStatus 迁移需要 |
| --- | --- | --- | --- |
| `github.com/gin-gonic/gin` | `v1.12.0` | HTTP 路由、中间件、静态服务/API | 保留 |

`server/go.sum` 中的 sonic、validator、quic-go、protobuf、`x/*` 等为 Gin 的间接依赖。Release C 删除表达式告警依赖。HermesStatus 首阶段不需要新增 Go Docker SDK、SMART 或 YAML 依赖，因为采集器仍由 Python 承担。若未来 Go 化，应单独进行依赖评审，不在等价迁移阶段顺带引入。

## NPM 与前端

| 项目 | 现状 | 迁移结论 |
| --- | --- | --- |
| `package.json` / lockfile | 不存在 | 无 npm 运行依赖 |
| 前端框架 | 原生 HTML/CSS/JavaScript | 保留，避免为迁移引入框架重写 |
| 图标库 | 不存在 | 无需新增；现有品牌 SVG 内联 |
| Node.js | 仅 CI `node --check web/js/app.js` | 保留 CI 语法检查工具，不是产品运行依赖 |

## Docker 依赖

| 依赖 | 1.0 | 2.0 基线 | 迁移后 |
| --- | --- | --- | --- |
| Client base | `alpine:3.13` | `alpine:3.13` | 建议升级到受支持 Alpine，并验证 psutil/smartctl |
| Server builder | Python/Debian + C++ toolchain | `golang:1.25-alpine` | 使用 2.0 Go builder |
| Server runtime | Debian + Nginx/Python/C++ | `alpine:3.22` + 静态 Go binary | 使用 2.0 runtime |
| Docker Engine | 客户端通过 Socket 读取 | 原生只用于运行容器 | 保留为 HS-009 数据源 |
| Docker Compose | 双容器 | 双容器 | 保留服务端/客户端两容器边界 |
| host network/PID | Client 使用 | 2.0 原生 client 使用 | host network 保留；host PID 仅 CLI 兜底需要 |
| privileged + `/dev` | HermesStatus 新增 | 2.0 原生无 | SMART 首阶段保留，后续最小化权限 |

## Git Submodule 与内嵌代码

| 类型 | 现状 | 处理 |
| --- | --- | --- |
| Git submodule | 无 `.gitmodules` | 无迁移事项 |
| `exprtk.hpp` | 1.0 C++ 仓库内嵌头文件 | Go 2.0 使用 `expr` module 后删除 |
| 自带 JSON/C 系统实现 | `server/include`, `server/src/*.c` | 随 C++ server 删除 |
| Telegram plugin | `plugin/` 原生历史目录 | 2.0 已删除，HermesStatus 页面不依赖 |

## 迁移后保留与删除

### 必须保留

- Python 3、psutil、PyYAML、smartmontools。
- Docker Engine Socket 访问能力。
- Hermes CLI 和每 Profile loopback API 可达性。
- Go 2.0 的 Gin、expr、CA 与时区依赖。

### 首阶段保留，后续评估

- `util-linux/nsenter`、host PID。
- 客户端 `privileged:true` 和全 `/dev` 挂载。
- Python exporter 与磁盘 JSON 中间快照。
- 原生 client 的 iproute2/procps。

### 可删除

- C/C++ 编译链、libcurl、libstdc++ runtime。
- Nginx、服务端 Python 管理 API、OpenSSL CLI 运行依赖。
- C++ vendored exprtk、C JSON/system 源码。
- 1.0 server 的 Python/Debian build args。

## 关联文档

- 后端文件：[BACKEND_DIFF.md](BACKEND_DIFF.md)
- 容器配置：[CONFIG_DIFF.md](CONFIG_DIFF.md)
- 废弃候选：[LEGACY.md](LEGACY.md)
- 迁移阶段：[MIGRATION_PLAN.md](MIGRATION_PLAN.md)
