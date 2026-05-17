# Coding Style — Project Standards

## When to use this skill

Apply when writing or reviewing any code in this project. These standards override generic defaults.

---

## Naming

| Context | Convention | Example |
|---------|-----------|---------|
| Variables, functions | `camelCase` | `getUserById` |
| Classes, types | `PascalCase` | `UserService` |
| Constants | `UPPER_SNAKE` | `MAX_RETRY_COUNT` |
| Files (JS/TS) | `kebab-case` | `user-service.ts` |
| Files (Python) | `snake_case` | `user_service.py` |
| Database columns | `snake_case` | `created_at` |
| API endpoints | `kebab-case` | `/api/user-profiles` |

**Descriptive names rule**: names must convey purpose without comments.
- ❌ `d`, `tmp`, `data`, `result`, `obj`
- ✅ `userProfile`, `retryCount`, `httpResponse`

---

## Functions

- One function = one logical operation
- Maximum 30 lines (excluding comments/whitespace)
- Parameters: maximum 3. More → use an options object/dataclass
- Return early for error cases — avoid deep nesting

```typescript
// ✅ Early return
async function getUser(id: string): Promise<User> {
  if (!id) throw new ValidationError('id required');
  const user = await db.users.findById(id);
  if (!user) throw new NotFoundError(`User ${id} not found`);
  return user;
}
```

---

## Error handling

- Use typed errors, not string messages
- Never swallow errors silently (`catch (e) {}` is forbidden)
- Log errors with context before re-throwing
- User-facing errors: generic message. Internal logs: full details

```typescript
// ✅ Typed error with context
try {
  await paymentService.charge(amount);
} catch (err) {
  logger.error('Payment failed', { userId, amount, error: err });
  throw new PaymentError('Payment could not be processed');
}
```

---

## Imports

- Absolute imports preferred over relative (if project supports it)
- Group order: stdlib → third-party → project → relative
- No circular imports — if you need to, extract to a shared module
- Never `import *` in production code

---

## Comments

- Comments explain WHY, not WHAT
- Code should be self-documenting — refactor before commenting
- TODO: `// TODO(name): description` — must have owner
- Forbidden: commented-out code (delete it, git has history)

---

## Test file conventions

- Mirror source structure: `src/users/service.ts` → `tests/users/service.test.ts`
- Describe blocks: noun phrases (`UserService`)
- Test names: `should <behavior> when <condition>`
- One assertion group per test case
