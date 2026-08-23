# 运维

## 正确理解状态

Server 生命周期时钟是权威来源。恢复状态在收到新的已接受上报前为 stale。健康的空采集不同于 unavailable，`not_configured` 也不同于 error。

以下是可见但不应被误判为整个设备故障的状态：

- 可选 Hermes Agent 未安装；
- USB bridge 可读取 SMART 属性但无 native return status；
- EasyTier peer/route/connector 采集为有效空结果；
- 可选 Lucky 业务模块没有配置对象。

真正的 SMART 失败、被拒绝的 Device v2 上报或传输失败必须保持为 failure/degraded。

## 日常诊断

先查看目标设备的生命周期状态、更新时间和 collection status，再对照 Client snapshot、Server 已接受投影和 Web 页面。部署问题应先比较运行中的 image digest/OCI revision 与目标不可变 revision，之后再排查应用行为。

只使用文档规定的固定诊断。不要进入容器、运行任意主机命令，或为了诊断展示问题而修改 router/Lucky/EasyTier 配置。

## 备份与恢复

计划重建前备份 Server state、Registry 配置和非秘密部署文件。restart 或 Compose down/up 测试时保留持久状态。恢复时从已知精确镜像与配置重建受影响服务，然后等待新的已接受上报再将恢复数据视为 fresh。

## EasyTier 观测

没有远端 peer 时，Direct/Relay/IPv6-UDP-Direct 应为“不可观测”。当前 2.0 在部分 2.6.4 输出中存在本机节点被计入 peer 汇总的已知限制；在修复前请以详细行而非汇总作为远端 peer 数量依据。
