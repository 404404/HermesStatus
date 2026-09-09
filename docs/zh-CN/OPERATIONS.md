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

## Device v2 状态升级与回滚

2.7 之后的第一轮采集诊断 Server 变更会持久化结构化解码证据，以及
EasyTier 显示计数元数据是否显式出现。磁盘状态中的格式仍标记为
`version: 2`，因此不能仅凭这个字符串推断可安全降级。隔离兼容验证已确认：

- 精确 2.7（`c4e3fd30e60843373594c936fb62e5908062f685`）写出的状态可以由
  新 Server 恢复；
- 精确 2.7 Server 可以在新状态存在时启动，但会拒绝恢复受影响设备，并将其
  保留为损坏孤儿状态。

升级 Server 前，应私有备份精确状态文件及其 `~` 备份，并把 Server/Client
不可变 digest 和配置/Registry 修订一并记录。已知状态文件绝对路径时，操作员可执行：

```sh
STATE_FILE=/absolute/path/to/server-state.json
BACKUP_DIR=/absolute/path/to/rollback-before-server-upgrade
install -d -m 0700 -- "$BACKUP_DIR"
cp --preserve=mode,timestamps -- "$STATE_FILE" "$BACKUP_DIR/"
[ ! -e "$STATE_FILE~" ] || cp --preserve=mode,timestamps -- "$STATE_FILE~" "$BACKUP_DIR/"
sha256sum -- "$BACKUP_DIR"/*
```

跨越该边界回滚不等于停止新 Client：先停止它以保证只有一个 Device v2 writer，
再停止新 Server；恢复精确的旧 Server/Client 镜像与配置，并在启动旧 Server 前恢复
升级前的状态副本。验证 Compose 后按 Server、匹配 Client 的顺序启动，保留重放保护
状态并确认只有一个 writer 在线。若没有升级前状态副本，此降级不具备资格；不要为了
让旧 Server 启动而清空状态或重放数据。

## EasyTier 观测

没有远端 peer 时，Direct/Relay/IPv6-UDP-Direct 应为“不可观测”。部分 2.6.4 输出包含本机 peer 时，Client 使用 own-peer-ID/`Local` 标记排除该行。若界面显示“其余明细未显示”，应以观察总数而非已显示行数判断规模。
