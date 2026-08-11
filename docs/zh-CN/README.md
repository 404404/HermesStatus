# HermesStatus 文档

[English](../README.md)

本文档集以 `2.3-preview` 分支的 2.3 Preview 源码为准。该分支用于集成和 21443 staging，不会自动推进到 `2.0`；真实双站点资格验证仍是前置条件。

| 文档 | 用途 |
| --- | --- |
| [架构](ARCHITECTURE.md) | 组件、数据流、页面范围与非目标。 |
| [配置](CONFIGURATION.md) | 服务端、客户端、Hermes、Lucky 与多设备配置。 |
| [设备配置编写指南](DEVICE_CONFIGURATION.md) | 设备名称权威来源、局域网地址字段、文件路径、Compose 挂载与示例。 |
| [部署](DEPLOYMENT.md) | Compose、生产部署与 SMART 设备权限边界。 |
| [安全](SECURITY.md) | 信任边界、凭据与安全暴露规则。 |
| [运维](OPERATIONS.md) | 健康检查、陈旧数据、升级与回滚。 |
| [开发](DEVELOPMENT.md) | 本地验证与 PR 流程。 |
| [EasyTier 监控设计](EASYTIER_MONITORING.md) | 只读数据边界、状态语义、Fixture 与资格验证。 |

中文文档与英文规范文档应在同一 PR 中同步更新。
