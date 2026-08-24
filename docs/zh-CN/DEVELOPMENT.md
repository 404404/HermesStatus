# 开发

从当前远端基线创建聚焦的 `codex/*` 分支。先读取远端状态，保留无关工作区变更，避免对已评审分支 rebase 或 force-push。使用小而可评审的 commit，在受保护分支合并前创建 Draft PR。只有用户明确授权才能更新 `2.0`。

## 必要检查

推送前按适用范围执行：

```bash
git diff --check
python3 -m unittest discover -s clients/tests
python3 -m unittest discover -s scripts/tests
go test ./...
go test -race ./...
go vet ./...
go build ./...
node --test web/js
docker compose config --quiet
```

同时运行仓库的合同、release-boundary 与 secret 检查。不得通过削弱校验器、跳过失败测试或修改分支保护来获得绿色结果。

## Review 与发布

修复有效的安全、数据完整性、身份、持久化、兼容性与 XSS 问题。Review 修复后需重新构建最终镜像；候选或生产部署必须使用最终已评审 commit，而不是早期候选。受控部署 helper 除非其源码被有意纳入评审，否则应与产品源码分离。
