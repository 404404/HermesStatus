# Development

Create focused `codex/*` branches from the current remote base.  Read remote
state first, preserve unrelated working-tree changes and avoid rebasing or
force-pushing a reviewed branch.  Use small, reviewable commits and create a
Draft PR before a protected-branch merge.  Only a user-authorized merge may
update `2.0`.

## Required checks

Run applicable checks before pushing:

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

Run the repository's contract, release-boundary and secret checks as well.
Do not weaken validators, skip failing tests or change branch protection to get
a green result.

## Reviews and releases

Address valid security, data-integrity, identity, persistence, compatibility
and XSS findings. Rebuild final images after review fixes; a candidate or
production deployment must run the final reviewed commit, not an earlier
candidate.  Keep deployment-only controlled helpers separate from product
source unless their source is intentionally tracked and reviewed.
