---
name: finishing-a-development-branch
description: Use when implementation is complete, all tests pass, and you need to decide how to integrate the work
---

# Finishing a Development Branch

**"Test verification → environment detection → present options → execute choice → cleanup."**

**Announce**: "I'm using the finishing-a-development-branch skill to wrap up this work."

## Step 1 — Test verification (mandatory gate)

```bash
npm test / cargo test / pytest / go test ./...
```

**If tests fail: stop immediately. Cannot proceed to Step 2.**

## Step 2 — Environment detection

| State | Menu | Cleanup |
|-------|------|---------|
| `GIT_DIR == GIT_COMMON` (normal repo) | Standard 4 options | No worktree to clean |
| `GIT_DIR != GIT_COMMON`, named branch | Standard 4 options | Based on origin |
| `GIT_DIR != GIT_COMMON`, detached HEAD | Reduced 3 options (no merge) | None (externally managed) |

## Step 4 — Present options

**Normal repo and named-branch worktree — exactly 4 options:**
```
Implementation complete. What would you like to do?

1. Merge back to <base-branch> locally
2. Push and create a Pull Request
3. Keep the branch as-is (I'll handle it later)
4. Discard this work

Which option?
```

**Detached HEAD — exactly 3 options:**
```
Implementation complete. You're on a detached HEAD (externally managed workspace).

1. Push as new branch and create a Pull Request
2. Keep as-is (I'll handle it later)
3. Discard this work

Which option?
```

## Step 5 — Execute choice

**Option 1: Local merge**
```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"
git checkout <base-branch>
git pull
git merge <feature-branch>
<test command>
# Only after successful merge → cleanup
git branch -d <feature-branch>
```

**Option 2: Push and create PR**
```bash
git push -u origin <feature-branch>
gh pr create --title "<title>" --body "..."
```
Do NOT clean up worktree — keep it for PR feedback iterations.

**Option 3: Keep as-is**
Do NOT clean up worktree.

**Option 4: Discard**
Ask first: "Type 'discard' to confirm."
Wait for exact confirmation → clean worktree → force delete branch.

## Step 6 — Worktree cleanup (Options 1 and 4 only)

Only clean worktrees under `.worktrees/`, `worktrees/`, or `~/.config/superpowers/worktrees/`:
```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"
git worktree remove "$WORKTREE_PATH"
git worktree prune
```

## Quick reference

| Option | Merge | Push | Keep worktree | Delete branch |
|--------|-------|------|---------------|---------------|
| 1. Local merge | ✓ | — | — | ✓ |
| 2. Create PR | — | ✓ | ✓ | — |
| 3. Keep as-is | — | — | ✓ | — |
| 4. Discard | — | — | — | ✓ (force) |

---

## sprint-system integration

**Used by**: `ci-cd-engineer` at the end of `/sprint` Phase 5 (Sprint Review)

In sprint-system, Option 2 (PR) is the standard path:
- Sprint branch pushed to GitHub
- `ci-cd-engineer` creates a PR with AC evidence
- PR requires CODEOWNERS review (4-eyes for milestone PRs)
- After PR is merged, `dod-handler.yml` fires `milestone.completed` event

Audit event on branch completion:
```bash
bash .claude/bin/audit-append.sh '{"event":"sprint.branch_finished","sprint":"<N>","option":"pr_created","pr_url":"<url>"}'
```
