# 开发

[English](../DEVELOPMENT.md) · [文档目录](README.md)

## 本地检查

在已审查工作树中执行：

```bash
go test ./...
(cd clients && python3 -m unittest discover)
(cd scripts/tests && python3 -m unittest discover)
docker compose -f docker-compose-server.yml config --quiet
docker compose -f docker-compose-client.yml config --quiet
```

开发时先运行最小相关测试，创建 PR 前运行受影响范围的完整检查。需要 Unix socket 或 Docker daemon 的测试必须在允许这些本地能力的环境执行。

## 变更边界

源代码、部署配置和文档应保持可审查。不要将运行环境修复与无关的 UI 或文档改写混在同一个 commit。生产类候选必须具备可识别的源代码 revision 和镜像溯源。

## Pull Request

创建聚焦分支并提交，然后向 `2.0` 创建 PR。等待必需 CI 和 Review 反馈；在同一分支修复可操作问题，运行行为改变后重新部署候选验证，并只在操作员确认后合并。
