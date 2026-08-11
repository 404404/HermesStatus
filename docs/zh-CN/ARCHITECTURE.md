# 架构

[English](../ARCHITECTURE.md) · [文档目录](README.md)

## 目标

HermesStatus 是面向显式配置主机的当前状态面板，不提供对主机、容器、Hermes、Lucky 或 EasyTier 的控制能力。主要页面为主页、Hardware、Docker、Lucky 和 EasyTier。

## 组件与数据流

```text
主机系统 / hwmon / SMART / 显式文件系统 probe / Docker / Hermes / Lucky / EasyTier
                         ↓
                    Python Client
                         ↓
         Legacy TCP Agent 或已认证 HTTPS 设备上报
                         ↓
                      Go Server
                         ↓
          /json/stats.json · /api/health · WebUI
```

Client 采集主机数据并形成 `hardware`、`docker`、`hermes`、`lucky`、`easytier` 五个结构化域。单个域可陈旧或不可用，不会阻止其余数据域上报。

Go Server 校验上报、保留最近一次接受的状态、持久化指定状态，并投影为 `/json/stats.json`。浏览器只读取这一份文档；页面切换不会额外请求数据。

## 页面范围

主页展示设备状态、CPU、内存、磁盘容量、EasyTier 远端节点与流量摘要、物理磁盘温度/SMART、Hermes Profile，以及已配置 Lucky/EasyTier 的状态与版本摘要。EasyTier 流量以一位小数、自动单位和单行的接收 / 发送 / 转发格式显示；Hermes Profile 表头显示 Agent 版本和配置数量。Hardware 位于主页之后，分为系统信息、文件系统/存储卷和物理磁盘。Docker 页面展示容器表格；Lucky 页面展示其配置与服务摘要；EasyTier 页面先展示逐命令采集状态卡片，再展示只读网络摘要。

`hardware.storage.physical_disks` 与 `hardware.storage.filesystems` 是两个独立且有数量限制的集合。Client 通过只读 block-device graph，将普通分区及通用的 LVM、MD RAID、device mapper 和 Btrfs/EXT4 存储栈解析为零个或多个物理磁盘 ID。文件系统绝不会被填入臆造的温度或 SMART 值。只采集运维人员配置的物理 SMART 设备和显式只读文件系统 probe 挂载。

系统身份以脱敏形式报告发行版/版本、内核、架构与来源。构建溯源同样只读：Server 报告构建元数据，选中的 Device 可报告 Client 构建元数据。revision 在构建时注入，预期与 OCI revision 一致；生产镜像不会在运行时调用 Git。环境是运维人员提供的部署标签，不能由主机端口推断。

常规主机网络吞吐、累计主机网络流量、运营商或三网延迟探测不是 HermesStatus 面板功能，文档不得将其描述为产品能力；即使 Legacy Agent 协议为兼容目的仍包含相关字段。此限制不包括独立的 EasyTier 接收 / 发送 / 转发计数器。

## 上报模式

### Legacy TCP

现有 Agent 建立 TCP 连接，以配置的用户名和密码认证，接收监控定义并发送状态更新。该模式继续服务于已配置的 Legacy 设备。

### Device v2

Device v2 默认关闭。启用后仅通过受配置安全代理保护的 `POST /api/v2/device-updates` 接收请求。设备提交唯一的 `X-HermesStatus-Device-ID`、Bearer 凭据和有大小限制的 JSON envelope。服务端按启动时 Registry 验证设备、credential digest 与身份，执行重放和限流检查，持久化接受的更新，并返回已脱敏的监控定义。

Registry 最多支持 16 台设备。自动发现、浏览器注册、远程控制、RBAC、多租户、数据库历史、WebSocket 与 SSE 均不在产品范围内。

## 2.3 Preview EasyTier 边界

`2.3-preview` 用于集成 2.3 工作并运行独立的 21443 staging，不代表推进到
`2.0`。EasyTier 只能通过现有 stats document 中经过验证、无秘密的扩展到达
Server。浏览器与其他页面共享 `/json/stats.json` 请求和已选择设备；不存在
独立 EasyTier 接口、计时器、管理通道或身份映射。Registry expectation 仅用于
比较诊断，绝不用于认证或设备身份。
