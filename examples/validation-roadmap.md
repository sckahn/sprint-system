# Project Roadmap

## Project goal
Sprint system validation: verify that the full sprint → DoD → milestone → project closure loop works end-to-end in a real repo.

## Definition of Done
All 3 ACs confirmed by human, milestone PR merged, project closed with audit attestation.

## Quality gates

| Gate | Threshold |
|------|-----------|
| Test coverage | ≥ 70% |
| Security Critical findings | 0 |
| Audit chain | verified (audit-verify.sh OK) |

## Budget
- Max sprints total: 3
- Max sprints per milestone: 3

## Active agents
spec-writer, backend-eng, code-reviewer, security-auditor, qa-tester, ci-cd-engineer

---

## Milestones

### M-val — Validation Sprint

- **Status**: pending
- **Assignee**: @your-github-username

- **Acceptance criteria**:

  - **AC-val.1**: A `hello_world()` function exists in `src/hello.py` and returns the string `"Hello, World!"`
    - Verifies: `tests/test_hello.py::test_hello_returns_correct_string`
    - Requires human signoff: yes

  - **AC-val.2**: The `hello_world()` function handles an optional `name` parameter, returning `"Hello, <name>!"` when provided
    - Verifies: `tests/test_hello.py::test_hello_with_name`
    - Requires human signoff: yes

  - **AC-val.3**: Running `pytest tests/` in CI passes with 0 failures and ≥70% coverage on `src/hello.py`
    - Verifies: CI test run output
    - Requires human signoff: yes
