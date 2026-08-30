# 安全

HermesStatus 被设计为只读。安全模型基于显式身份、窄范围采集 allowlist、各边界校验和最小权限部署。

## 身份与 secret

Device v2 使用 TLS 和每设备 token。Server 只保存 token digest；Client 从 root-owned 只读文件读取 token 与 CA。不要记录、输出、为报告 hash、提交或放入命令行、环境变量值、fixture、stats 文档或 UI 的凭据。

## 采集边界

Collector 使用固定 source allowlist 和 argv 数组，拒绝任意命令、远程 URL、redirect、原始配置、凭据和敏感 EasyTier 对象。Lucky 仅允许 loopback；EasyTier 仅允许配置的 loopback RPC 和只读 CLI 查询。运行时 allowlist 不含管理、凭据、路由、端口转发、日志或服务控制命令。

## 主机权限

不要使用 privileged、`SYS_ADMIN`、Docker socket、整个 `/dev` 或主机根目录。只映射明确 SMART 设备，并在需要时授予 `SYS_RAWIO`。文件系统和 DSM probe 使用固定窄范围只读挂载。受控部署 helper 必须只提供固定子命令与路径，不能变成通用 `sudo`、Docker 或 shell 权限。

## 数据处理

Server 对 count、字符串、counter、timestamp、CIDR 与 enum 设定边界。未知敏感字段和 raw object 会被丢弃。HTML 使用安全转义，测试覆盖恶意值。持久化以原子方式应用已接受更新，并拒绝 stale/conflict mutation。

## 漏洞报告

不要在 issue 中包含 secret 或真实基础设施标识。请通过仓库的私有安全联系渠道或维护者渠道提交最小可复现、已脱敏的描述。

## UniFi 远端观测边界

UniFi V1 不提供通用 `run_remote(command)` 接口。profile 只能引用代码侧 symbolic source ID；Client 通过 argv 数组执行固定、打包的只读 SSH script，并使用有界 timeout、`setsid --wait`、keyboard-interactive 认证及 `StrictHostKeyChecking=yes`。password 仅由短生命周期的本地 askpass helper 从经校验的受保护文件读取；不会写入 argv、日志、stats、fixture、UI、镜像 label 或环境变量值。host-key 失败只是安全的遥测错误，绝不是接受替换 key 的理由。Client 不安装 key、不扫描网络、不修改 UniFi 配置、不读取配置数据库，也不执行风扇/PWM/存储控制命令。
