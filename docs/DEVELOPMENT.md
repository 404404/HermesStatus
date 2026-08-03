# Development

[中文](zh-CN/DEVELOPMENT.md) · [Documentation index](README.md)

## Local checks

Run checks from the reviewed worktree:

```bash
(cd server && go test ./...)
(cd clients && python3 -m unittest discover)
(cd scripts/tests && python3 -m unittest discover)
docker compose -f docker-compose-server.yml config --quiet
docker compose -f docker-compose-client.yml config --quiet
```

Run the smallest relevant test while developing, then the broader affected
suite before opening a pull request. Tests that need a Unix socket or Docker
daemon must run where those local primitives are permitted.

## Change boundaries

Keep source changes, deployment configuration, and documentation reviewable.
Do not mix an operational deployment repair with unrelated UI or documentation
rewrites in one commit. A production-like candidate needs an identifiable source
revision and image provenance.

## Pull requests

Create a focused branch and commit, then open a pull request against `2.0`.
Wait for required CI and review feedback. Fix actionable findings on the same
branch, redeploy a candidate when runtime behavior changes, and merge only with
operator confirmation.
