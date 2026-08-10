# 开发

[English](../DEVELOPMENT.md) · [文档目录](README.md)

## 本地检查

在已审查工作树中执行：

```bash
(cd server && go test ./...)
(cd clients && python3 -m unittest discover)
(cd scripts/tests && python3 -m unittest discover)
docker compose -f docker-compose-server.yml config --quiet
docker compose -f docker-compose-client.yml config --quiet
```

开发时先运行最小相关测试，创建 PR 前运行受影响范围的完整检查。需要 Unix socket 或 Docker daemon 的测试必须在允许这些本地能力的环境执行。

## 变更边界

源代码、部署配置和文档应保持可审查。不要将运行环境修复与无关的 UI 或文档改写混在同一个 commit。生产类候选必须具备可识别的源代码 revision 和镜像溯源。

## Pull Request

创建聚焦的 `codex/2.3-*` 分支并提交，然后向 `2.3-preview` 创建 Draft PR。等待
必需 CI 和 Review 反馈；在同一分支修复可操作问题，运行行为改变后重新部署最终候选，
并保持 Draft，直到操作员手动合并。不得自动 Mark Ready、Merge 或将 Preview 推进到
`2.0`。

EasyTier 改动除常规 Python、Go、race、vet、build、Node、Compose、contract 与 secret
门禁外，还需要 synthetic 状态 Fixture 和真实 loopback GK50 采集检查。Synthetic 拓扑
状态必须始终明确标记。
