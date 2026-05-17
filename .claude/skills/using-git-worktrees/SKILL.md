---
name: using-git-worktrees
description: Use when starting feature work that needs isolation from current workspace or before executing implementation plans
---

# Using Git Worktrees

**"Detect existing isolation first. Use native tools. Fall back to git. Never fight the harness."**

**Announce**: "I'm using the using-git-worktrees skill to set up an isolated workspace."

## Step 0 — Detect existing isolation

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

**Submodule guard**: `GIT_DIR != GIT_COMMON` is also true inside git submodules. Before concluding you're in a worktree, confirm it's not a submodule:
```bash
git rev-parse --show-superproject-working-tree 2>/dev/null
```

| Condition | Action |
|-----------|--------|
| `GIT_DIR != GIT_COMMON` (not a submodule) | Already in a linked worktree → skip to Step 3 |
| `GIT_DIR == GIT_COMMON` | Normal repo checkout → proceed |

## Step 1a — Native worktree tools (preferred)

If platform provides native tools (`EnterWorktree`, `WorktreeCreate`, `/worktree`, `--worktree` flag): use them.
Only fall back to Step 1b if no native tools exist.

## Step 1b — Git worktree fallback

Directory selection priority:
1. Check for declared worktree directory preference in project instructions
2. Check for existing project-local worktree directory (`.worktrees` or `worktrees`)
3. Check for existing global directory (`~/.config/superpowers/worktrees/$project`)
4. Default: `.worktrees/` in project root

**Safety check** (project-local directories only):
```bash
git check-ignore -q .worktrees 2>/dev/null || git check-ignore -q worktrees 2>/dev/null
```
If not ignored: add to `.gitignore`, commit, then proceed.

```bash
git worktree add "$path" -b "$BRANCH_NAME"
cd "$path"
```

## Step 3 — Project setup

```bash
if [ -f package.json ];     then npm install; fi
if [ -f Cargo.toml ];       then cargo build; fi
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
if [ -f go.mod ];           then go mod download; fi
```

## Step 4 — Clean baseline verification

```bash
npm test / cargo test / pytest / go test ./...
```

- Tests fail: report failures, ask whether to proceed or investigate
- Tests pass: report ready

## Quick reference

| Situation | Action |
|-----------|--------|
| Already in a linked worktree | Skip creation (Step 0) |
| Inside a submodule | Treat as normal repo |
| Native worktree tools available | Use them (Step 1a) |
| No native tools | Git worktree fallback (Step 1b) |
| `.worktrees/` exists | Use it (verify ignored) |
| Permission error | Sandbox fallback, work in current location |
| Baseline tests fail | Report + ask |

---

## sprint-system integration

**Used by**: `ci-cd-engineer`, `backend-eng`, `frontend-eng`

In sprint-system, each implementation agent runs in an isolated worktree so parallel agents don't conflict:
- Sprint branch: `sprint/<N>-<feature>`
- Worktree path: `.worktrees/sprint-<N>-<agent>`

The PM coordinator coordinates branch naming before dispatching parallel agents in Phase 2.
After all agents complete and `interface-validator` clears, `ci-cd-engineer` merges worktrees back using `finishing-a-development-branch`.
