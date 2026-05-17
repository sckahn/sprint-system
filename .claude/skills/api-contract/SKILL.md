# API Contract — Standards and Conventions

## When to use this skill

Apply when designing, implementing, or reviewing any API endpoint (REST or GraphQL) or inter-service interface.

---

## REST conventions

### URLs

```
GET    /api/v1/users              # list
POST   /api/v1/users              # create
GET    /api/v1/users/:id          # get one
PATCH  /api/v1/users/:id          # partial update
DELETE /api/v1/users/:id          # delete

GET    /api/v1/users/:id/orders   # nested resource
```

Rules:
- Plural nouns, never verbs in URLs
- `kebab-case` for multi-word segments
- Version prefix: `/api/v1/`
- Query params for filtering: `?status=active&page=2&limit=20`

### Request body

```json
{
  "email": "user@example.com",
  "displayName": "Jane Doe"
}
```

- `camelCase` field names
- No `id` or audit fields in request body (server-assigned)
- Required fields: validated and 400 returned if missing

### Response envelope

```json
{
  "data": { ... },
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-01-01T00:00:00Z"
  }
}
```

List responses:
```json
{
  "data": [ ... ],
  "meta": {
    "total": 100,
    "page": 1,
    "limit": 20,
    "requestId": "uuid"
  }
}
```

### HTTP status codes

| Status | Meaning |
|--------|---------|
| 200 | Success (GET, PATCH) |
| 201 | Created (POST) |
| 204 | No content (DELETE) |
| 400 | Validation error (bad request) |
| 401 | Not authenticated |
| 403 | Authenticated but not authorized |
| 404 | Resource not found |
| 409 | Conflict (duplicate, stale update) |
| 422 | Semantic validation failed |
| 429 | Rate limited |
| 500 | Internal server error (never expose details) |

### Error response

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Email is required",
    "fields": {
      "email": "required"
    },
    "requestId": "uuid"
  }
}
```

- `code`: machine-readable constant (`UPPER_SNAKE`)
- `message`: human-readable, safe for display
- `fields`: field-level details for validation errors
- Never include stack traces, file paths, or internal IDs in error responses

---

## Versioning policy

- Breaking changes require a new version (`/v1/` → `/v2/`)
- Breaking: removing a field, changing a field type, changing auth requirement
- Non-breaking: adding optional fields, adding endpoints
- Old versions: deprecated (warning header), supported for 6 months minimum

---

## Authentication header

```
Authorization: Bearer <jwt-token>
```

- All authenticated endpoints validate token on every request
- Expired tokens → 401 (never 403)
- Invalid permissions → 403

---

## Pagination

Always paginate list endpoints. Default limit: 20, max: 100.

```
GET /api/v1/orders?page=2&limit=20
```

Response includes `meta.total`, `meta.page`, `meta.limit`.

---

## GraphQL (if used)

- Queries: read-only, cached
- Mutations: state changes, never cached
- Subscriptions: real-time only when polling is insufficient
- Error format: GraphQL spec errors array with `extensions.code`
- Depth limit: 5 levels max to prevent DoS
