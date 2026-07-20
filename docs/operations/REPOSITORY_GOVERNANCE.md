# Repository governance

HermesStatus uses `2.0` as its default integration and release branch. The `1.0` branch is retained as the legacy C++ baseline and is not covered by the `2.0` release gate.

## Protected branch

`2.0` has one Classic branch protection rule. No Repository ruleset is configured.

| Rule | Configuration |
| --- | --- |
| Pull request required | Enabled |
| Required status checks | `contracts`, `go`, `python`, `frontend`, `compose`, `images`, `security` |
| Check provider | GitHub Actions App ID `15368` |
| Branch must be up to date | Enabled |
| Conversation resolution | Required |
| Required approvals | `0` |
| Administrator enforcement | Enabled |
| Force pushes | Disabled |
| Branch deletion | Disabled |
| Linear history | Not required |
| Merge commit | Available |

The zero-approval policy keeps a single-maintainer repository operable while still requiring the PR, current-head CI, and conversation-resolution gates. Administrator enforcement prevents direct pushes from bypassing the rule. Repository administrators can still change repository settings, so account security remains part of the trust boundary.

The repository continues to permit merge commits. Branch protection does not require a linear history and does not change the repository's other merge-method settings.

## Required-check evidence

The check names and App ID were read from commit `20b5e497df7a2cd982b54378751db7c8f896548d`, the merge commit for PR #9 on `2.0`. GitHub Actions run `29752853429` completed successfully for all seven jobs.

## Branch lifecycle

Temporary branches may be deleted only when all of the following are true:

1. The associated PR is merged.
2. The branch HEAD is reachable from `2.0`.
3. No open PR uses the branch.
4. The branch is neither the default branch nor a protected or long-lived branch.
5. No unmerged branch depends on it.
6. The exact branch name has been approved for deletion.

The long-lived `1.0` and `2.0` branches must not be removed by routine cleanup. Local branches are outside remote cleanup and require separate approval.

The merged temporary branches for PRs #2 through #9 were removed after this checklist was applied. Only `1.0` and `2.0` remained on the remote after pruning; the local `codex/release-d-repository-governance` documentation branch was retained and was not pushed.

## Rollback

Removing the Classic protection through GitHub's branch-protection settings or the `DELETE /repos/404404/HermesStatus/branches/2.0/protection` endpoint restores the previous unprotected state. A rollback must be explicitly approved because it re-enables direct pushes, force pushes, and branch deletion. It must not alter the default branch or create a parallel Ruleset.

## Scope boundary

Repository governance does not deploy software, change runtime configuration, create tags or releases, or validate the production host. See [validation](../testing/VALIDATION.md), [security](SECURITY.md), and [known limitations](KNOWN_LIMITATIONS.md).
