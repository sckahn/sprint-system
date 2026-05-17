---
name: receiving-code-review
description: Use when receiving code review feedback — as a reviewer or as an implementer receiving review
---

# Receiving Code Review

**"Technical evaluation, not emotional performance."**

**"Verify then implement. Ask before assuming. Technical accuracy over social comfort."**

## Response pattern (follow this order)

1. Read completely without reacting
2. Restate requirements in your own words (or ask questions)
3. Check against actual codebase reality
4. Evaluate if technically sound for this specific codebase
5. Provide technical confirmation or grounded counter
6. Implement one at a time, test each

## Absolute prohibition: performative agreement

Never say:
- "That's a great point!"
- "You're absolutely right!"
- "I'll implement that right away!" (before verifying)
- Any expression of enthusiasm about feedback

Instead: restate the technical requirement, ask clarifying questions, provide grounded counter, or just start working.

## When feedback is unclear

"I understand items 1, 2, 3, 6. Items 4 and 5 need clarification before I proceed."

## When to counter

Counter with technical grounds when feedback would:
- Break existing functionality
- Lack full context
- Violate YAGNI
- Be technically incorrect for this stack
- Ignore legacy/compatibility requirements
- Conflict with architectural decisions

Counter format:
"I'd push back on [X]: [technical reason]. The current approach [Y] because [Z]. 
If I'm missing context, please clarify [specific question]."

## When feedback is correct

- "Fixed. [Brief description]"
- "Good catch — [specific issue]. Fixed at [location]."
- Or just fix it and show the code

**No thanks. Action proves you heard the feedback.**

## Conclusion

External feedback = proposals to evaluate, not commands to follow.
Verify. Question. Then implement.
No performative agreement. Always technical rigor.

---

## sprint-system integration

**Used by**: `code-reviewer` (when the agent receives counter-arguments from implementers) and by `backend-eng`, `frontend-eng` (when receiving `code-reviewer` findings)

In sprint-system, the principle of "technical counter over social compliance" is critical for the separation-of-duties model. An implementer who silently accepts every finding is as dangerous as one who silently rejects every finding.

When a counter is made, it must be logged:
```bash
bash .claude/bin/audit-append.sh '{"event":"review.counter_raised","ac_id":"<id>","finding":"<finding_id>","counter":"<technical_reason>"}'
```
The PM coordinator decides if the counter is valid. Human escalation if disagreement persists.
