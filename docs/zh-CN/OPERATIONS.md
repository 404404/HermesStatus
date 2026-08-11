# 运维

[English](../OPERATIONS.md) · [文档目录](README.md)

## 只读检查

每次排障先检查服务端健康、当前状态投影和 Compose 服务状态：

```bash
curl -fsS http://127.0.0.1:<web-port>/api/health
curl -fsS http://127.0.0.1:<web-port>/json/stats.json
docker compose -p <project> ps
```

只检查与故障相关的字段；不要打印 credential 或原始配置。

## 数据解释

设备在线不代表 `hardware`、`docker`、`hermes` 或 `lucky` 域一定新鲜可用。读取数值前先检查每个域的 `error`、`stale` 和更新时间。SMART 权限失败属于不可用数据，不能被解读为磁盘健康，也不能静默显示成普通 `unknown`。

## 升级与回滚

变更前记录 Compose 项目、镜像 ID、源代码 revision、端口、数据路径、健康状态和重启次数。备份服务端状态与非秘密部署配置。在独立候选环境构建并验证后，只重建受影响服务。

回滚时恢复已记录的镜像引用和部署配置，同时保留现有服务端数据目录。不要创建第二个活动写入者，也不要盲目覆盖在线状态。

## EasyTier 解读

先看采集状态，再解读详细表。命令 error 或 timeout 表示该表不可用，不是真实空结果。
`fresh` 只有在 Server 时钟接受新的报告后才成立；从持久化恢复后必须保持 stale，直到
收到新报告。远端 Peer 为 0 是健康状态，Direct、Relay 与 IPv6 UDP Direct 都是
`not_observable`。

已验证的 GK50 基线为 `2.6.4-8428a89d` 且远端 Peer 为 0。真实 Synology 双站点、
IPv6 UDP Direct、TCP fallback、远端 `192.168.88.0/24` 和 Direct/Relay 行为仍待
资格验证，不是当前运维故障。
