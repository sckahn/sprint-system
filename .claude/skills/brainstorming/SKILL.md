---
name: brainstorming
description: Use when a new feature, initiative, or complex problem needs design exploration before implementation begins
---

# Brainstorming

**"Do not write any code, scaffold anything, or take any implementation action until you have presented a design and the user has approved it."**

No exceptions. Even if the project seems simple.

## 9-step process

1. **Explore** project context through existing files and documentation
2. **Provide visual aids** if helpful (ASCII diagrams, option tables)
3. **Ask clarifying questions** — one at a time, prefer multiple-choice when possible
4. **Propose 2–3 approaches** with explicit trade-offs for each
5. **Present the design** section by section and ask for approval
6. **Write the design document** to `docs/superpowers/specs/YYYY-MM-DD-<feature>.md`
7. **Self-review** the spec for completeness
8. **Ask the user to review** the written spec
9. **Hand off** to `writing-plans` skill for implementation planning

## Design quality criteria

Each design must address:
- **Architecture**: components, their boundaries, and responsibilities
- **Interfaces**: how components communicate
- **Data flow**: what data moves where
- **Error handling**: failure modes and recovery
- **Testing approach**: how correctness will be verified

Each component must have:
- One clear purpose
- Well-defined interfaces
- No hidden dependencies

## Design checkpoint rules

- Never skip the explicit approval step
- One clarifying question at a time
- "Looks good" is not approval — get confirmation that the design is accepted
- If requirements are contradictory, surface the contradiction before designing

---

## sprint-system integration

**When to invoke**: at the start of `/roadmap init` or when a new milestone needs architecture exploration before spec-writer produces ACs.

**Sequence**: `brainstorming` → `writing-plans` → `executing-plans` → `/sprint`

The `architect` agent uses this skill when designing ADRs. The PM coordinator invokes brainstorming at the milestone level when the design is unclear or cross-cutting.

Design documents are stored at `docs/superpowers/specs/` and referenced in ADRs at `docs/adr/`.
