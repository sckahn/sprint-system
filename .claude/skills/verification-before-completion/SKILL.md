---
name: verification-before-completion
description: Use before claiming any task, feature, fix, or deliverable is complete
---

# Verification Before Completion

**"Evidence before claims, always."**

Claiming completion without verification is lying.

## 5 mandatory verification gates

1. **Identify** the command that proves your claim
2. **Execute** the full command fresh (do not reuse old output)
3. **Read** the complete output and check the exit code
4. **Verify** the output confirms your claim
5. **Then** — and only then — make the claim

**Skipping any step = lying, not verifying.**

## Red flags to avoid

- Hedging language: "should", "probably", "seems to"
- Expressing satisfaction before verification: "Great!", "Done!"
- Committing immediately before verification
- Trusting agent reports without independent verification

## Scope

Apply to **every** variation of success/completion claims:
- Exact phrases
- Paraphrases
- Implied success
- Any communication suggesting completion or correctness

## The rule

**Run the command. Read the output. Then claim the result.**

This is non-negotiable.

---

## sprint-system integration

**Applies to**: every specialist agent before reporting results to the PM coordinator

Required evidence before any agent says "done":
- `backend-eng`: test suite output showing 0 failures
- `frontend-eng`: build output + accessibility check
- `qa-tester`: pytest/vitest output with pass counts
- `security-auditor`: scan output with CVE count
- `code-reviewer`: findings JSON with `overall` field
- `ci-cd-engineer`: CI status URL or `gh run view` output

**AC evidence_ready event** may only be appended when verification is complete.
The PM coordinator MUST NOT accept "I believe the tests pass" — only actual output.
