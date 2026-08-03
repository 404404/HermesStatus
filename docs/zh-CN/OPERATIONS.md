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
