---
name: test-driven-development
description: Use when implementing any feature or bugfix, before writing implementation code
---

# Test-Driven Development

**"NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST"**

Without seeing the test fail, you don't know if you've written the right test.
Violating the letter of the rule is violating the spirit of the rule.

## The Iron Law

Wrote code first? **Delete it and start over.** No exceptions. No "keeping it for reference." Delete means delete.

## Red-Green-Refactor

### RED — Write a failing test

- Test one behavior
- Clear name
- Use real code (mocks only if unavoidable)

```typescript
test('retries failed operations 3 times', async () => {
  let attempts = 0;
  const operation = () => {
    attempts++;
    if (attempts < 3) throw new Error('fail');
    return 'success';
  };
  const result = await retryOperation(operation);
  expect(result).toBe('success');
  expect(attempts).toBe(3);
});
```

### VERIFY RED — Mandatory. Never skip.

- Confirm the test **fails** (not errors)
- Confirm it's the expected failure message
- Confirm it fails because the feature is absent (not a typo)

### GREEN — Write minimum code

Only the simplest code to make the test pass.
No extra features, no refactoring, no "improvements."

### REFACTOR — Clean up

- Remove duplication, improve names, extract helpers
- Keep all tests passing
- Add zero new behavior

## Common rationalizations — debunked

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks too. A test takes 30 seconds. |
| "I'll test it later" | A test that immediately passes proves nothing. |
| "Post-tests achieve the same goal" | Post-test = "What does this do?" / Pre-test = "What should this do?" |
| "Deleting N hours of work is waste" | Sunk cost fallacy. Unverified code is technical debt. |
| "TDD is dogmatic" | TDD is pragmatic: less debugging, regression prevention, behavior documentation, enables refactoring. |

## Completion checklist

- [ ] Tests exist for every new function/method
- [ ] Each test confirmed failing before implementation
- [ ] Each test failed for the expected reason
- [ ] Minimal code written to make each test pass
- [ ] All tests pass
- [ ] Output is clean (no errors, no warnings)
- [ ] Real code used (mocks only where unavoidable)
- [ ] Edge cases and error handling covered

---

## sprint-system integration

**Applies to**: `backend-eng`, `frontend-eng`, `db-engineer`, `qa-tester`

When these agents write implementation code, they MUST follow TDD.
`qa-tester` is the guardian: if evidence shows the test was not written first, `qa-tester` flags it.
The sprint PM coordinator checks: each AC's evidence must include a failing-test-first record.
