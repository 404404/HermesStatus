# 架构

[English](../ARCHITECTURE.md) · [文档目录](README.md)

## 目标

HermesStatus 是面向显式配置主机的当前状态面板，不提供对主机、容器、Hermes 或 Lucky 的控制能力。主要页面为主页、Docker 和 Lucky。

## 组件与数据流

```text
主机系统 / hwmon / SMART / Docker / Hermes / Lucky
                         ↓
                    Python Client
                         ↓
         Legacy TCP Agent 或已认证 HTTPS 设备上报
                         ↓
                      Go Server
                         ↓
          /json/stats.json · /api/health · WebUI
```

Client 采集主机数据并形成 `hardware`、`docker`、`hermes`、`lucky` 四个结构化域。单个域可陈旧或不可用，不会阻止其余数据域上报。

Go Server 校验上报、保留最近一次接受的状态、持久化指定状态，并投影为 `/json/stats.json`。浏览器只读取这一份文档；主页、Docker 与 Lucky 页面切换不会额外请求数据。

## 页面范围

主页展示设备状态、CPU、内存、磁盘容量、主机与 CPU 身份、硬件温度/SMART、Hermes Profile，以及已配置 Lucky 的摘要。Docker 页面展示容器表格；Lucky 页面展示其配置与服务摘要。

网络吞吐、累计网络流量、运营商或三网延迟探测不是 HermesStatus 面板功能，文档不得将其描述为产品能力；即使 Legacy Agent 协议为兼容目的仍包含相关字段。

## 上报模式

### Legacy TCP

现有 Agent 建立 TCP 连接，以配置的用户名和密码认证，接收监控定义并发送状态更新。该模式继续服务于已配置的 Legacy 设备。

### Device v2

Device v2 默认关闭。启用后仅通过受配置安全代理保护的 `POST /api/v2/device-updates` 接收请求。设备提交唯一的 `X-HermesStatus-Device-ID`、Bearer 凭据和有大小限制的 JSON envelope。服务端按启动时 Registry 验证设备、credential digest 与身份，执行重放和限流检查，持久化接受的更新，并返回已脱敏的监控定义。

Registry 最多支持 16 台设备。自动发现、浏览器注册、远程控制、RBAC、多租户、数据库历史、WebSocket 与 SSE 均不在产品范围内。
