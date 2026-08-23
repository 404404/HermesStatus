# 部署

从已评审的不可变 revision 部署 Server 与 Client。变更服务前记录完整 Git revision、镜像 digest、OCI revision label、Compose project、端口、挂载、状态路径与重启次数。

## 标准流程

1. 校验 Server Registry/凭据与 Client 配置。
2. 构建或拉取来自同一 revision 的精确 Server/Client 镜像。
3. 备份状态与非秘密部署配置。
4. 只重建受影响服务。
5. 校验 health、重启次数、镜像 digest/revision 与已接受的 Device v2 上报。
6. 校验 `/health`、`/json/stats.json` 与相关页面。

不能以可变 tag 作为资格验证证据。运行容器的 OCI revision label 与 digest 必须匹配目标 revision。

## Device v2 部署

Client 必须使用固定 JSON 配置和 Device token/CA 的只读挂载。不要向 Device v2 Client 注入 Legacy 的 `SERVER`、`PORT`、用户名或密码变量。preflight 失败不得修改容器；重建前必须保留精确 rollback target。

## 共存与回滚

不同部署须通过 Compose project、容器、网络、状态、配置与凭据隔离。资格验证另一部署时，不得停止或重建无关稳定服务。真实 post-deploy 失败时，只能回滚到重建前记录的精确状态，不能在回滚中删除持久卷。

## 部署后验证

确认成功上报会变为 fresh，恢复状态在下一次已接受上报前为 stale，浏览器仍经现有 stats 文档读取数据。确认日志、进程参数、环境输出、stats 投影与 UI 均不包含 secret。
