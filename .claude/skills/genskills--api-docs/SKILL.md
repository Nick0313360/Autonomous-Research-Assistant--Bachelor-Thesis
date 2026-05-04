---
name: genskills:api-docs
description: >
  Generate API documentation - OpenAPI/Swagger specs, endpoint references,
  request/response examples. Triggers on: "API docs", "document API",
  "generate API reference", "swagger", "openapi spec".
user-invocable: true
argument-hint: "[api directory or 'all'] [--format openapi|markdown|inline] [--output <path>]"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npm run*), Bash(npx *), Bash(git diff*)"
genskills-version: "1.3.0"
genskills-category: "documentation"
genskills-depends:
  - genskills:doc-gen
---

# API Documentation Generator

Generate comprehensive API documentation.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any API documentation conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Check for existing API docs: `docs/api/`, `openapi.yaml`, `openapi.json`, `swagger.json`, `swagger.yaml`
- Check for existing doc generation tools: `typedoc`, `swagger-jsdoc`, `redoc`, `stoplight`, `tsoa`, `@nestjs/swagger`

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- First positional: API directory path or "all" for full project scan
- `--format`: output format - "openapi" | "markdown" | "inline" | "redoc" (default: auto-detect)
- `--output`: output file or directory path (default: "docs/api/")
- `--version`: API version string for OpenAPI spec (default: from package.json)
- `--base-url`: API base URL for examples (default: "http://localhost:3000")
- `--changed`: only document endpoints changed since last commit
- `--update`: update existing docs instead of regenerating

If no arguments, scan the full project for API routes.

### Step 2: Discover API Endpoints
Scan for route/endpoint definitions by framework:

| Framework | Route Patterns | Where to Look |
|---|---|---|
| **Express** | `app.get/post()`, `router.*`, `Router()` | `routes/`, `controllers/` |
| **Fastify** | `fastify.get/post()`, route schema objects | `routes/`, `plugins/` |
| **Hono** | `app.get/post()`, `Hono()`, `app.route()` | `routes/`, `src/` |
| **Next.js App** | `app/api/**/route.ts` (GET/POST/PUT/DELETE/PATCH exports) | `app/api/` |
| **Next.js Pages** | `pages/api/**` | `pages/api/` |
| **Remix** | `action`/`loader` exports in route files | `app/routes/` |
| **NestJS** | `@Get()`, `@Post()`, `@Controller()`, `@ApiProperty()` | `src/**/*.controller.ts` |
| **FastAPI** | `@app.get/post()`, `@router.*`, `APIRouter()` | `app/`, `routers/` |
| **Django REST** | `urlpatterns`, `@api_view`, `ViewSet`, `ModelSerializer` | `urls.py`, `views.py` |
| **Flask** | `@app.route()`, `Blueprint` | `app.py`, `routes/` |
| **tRPC** | `router()`, `procedure`, `.query()`, `.mutation()` | `server/`, `trpc/` |
| **GraphQL** | `type Query`, `type Mutation`, resolvers | `schema/`, `graphql/` |
| **Go (Gin/Echo/Chi)** | `r.GET/POST()`, `e.GET/POST()`, handler functions | `handlers/`, `routes/` |

### Step 3: Extract Endpoint Details
For each endpoint, extract:

**Core information:**
- **Method**: GET, POST, PUT, DELETE, PATCH, OPTIONS
- **Path**: URL pattern with parameters (e.g., `/api/users/:id`)
- **Summary**: Brief description of what the endpoint does
- **Description**: Detailed explanation of behavior, side effects

**Request details:**
- **Path parameters**: names, types, validation constraints, examples
- **Query parameters**: names, types, required/optional, defaults, examples
- **Request body**: schema from TypeScript types, Zod schemas, Pydantic models, class-validator DTOs
- **Headers**: required headers (Authorization, Content-Type, custom headers)
- **Content-Type**: accepted request content types

**Response details:**
- **Success responses**: all success status codes (200, 201, 204) with response body schemas
- **Error responses**: 400 (validation), 401 (unauthorized), 403 (forbidden), 404 (not found), 409 (conflict), 422 (unprocessable), 429 (rate limited), 500 (server error)
- **Response headers**: pagination headers, rate limit headers, cache headers

**Metadata:**
- **Auth**: authentication requirements (Bearer token, API key, session cookie, OAuth scope, public)
- **Rate limiting**: limits if documented or implemented via middleware
- **Middleware**: notable middleware (validation, auth, CORS, caching)
- **Tags/Groups**: resource grouping for organization
- **Deprecation**: deprecated endpoints with migration notes

### Step 4: Generate Documentation
Choose format based on project context or `--format` argument:

**OpenAPI 3.1 YAML** (preferred for API-first projects):
```yaml
openapi: 3.1.0
info:
  title: Project API
  version: 1.0.0
  description: API description from project metadata
servers:
  - url: http://localhost:3000
    description: Development
  - url: https://api.example.com
    description: Production
paths:
  /api/users:
    get:
      summary: List users
      tags: [Users]
      security:
        - bearerAuth: []
      parameters:
        - name: page
          in: query
          schema:
            type: integer
            default: 1
        - name: limit
          in: query
          schema:
            type: integer
            default: 20
            maximum: 100
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UserList'
              example:
                data:
                  - id: "usr_123"
                    name: "Jane Doe"
                    email: "jane@example.com"
                pagination:
                  page: 1
                  total: 42
        '401':
          $ref: '#/components/responses/Unauthorized'
components:
  schemas:
    # Generated from TypeScript types, Zod schemas, Pydantic models
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
```

- Generate schemas from TypeScript types, Zod schemas, or Pydantic models
- Include realistic example values (plausible fake data, never real credentials)
- Add `$ref` for reusable schemas, responses, and parameters

**Markdown** (for docs/ directory or README-based projects):
```markdown
# API Reference

## Authentication
All endpoints require a Bearer token unless marked as public.
```http
Authorization: Bearer <token>
```

## Users

### List Users
`GET /api/users`

**Query Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| page | integer | No | 1 | Page number |
| limit | integer | No | 20 | Items per page (max: 100) |

**Response:** `200 OK`
```json
{
  "data": [{ "id": "usr_123", "name": "Jane Doe" }],
  "pagination": { "page": 1, "total": 42 }
}
```

**Errors:**
| Status | Description |
|---|---|
| 401 | Missing or invalid auth token |
| 429 | Rate limit exceeded |
```

- Group by resource (Users, Products, Orders, etc.)
- Include curl examples for each endpoint
- Include request/response JSON examples with realistic data

**Inline** (JSDoc/docstring on route handlers):
```typescript
/**
 * List users with pagination.
 *
 * @route GET /api/users
 * @group Users
 * @security bearerAuth
 * @param {number} [page=1] - Page number
 * @param {number} [limit=20] - Items per page (max 100)
 * @returns {UserListResponse} 200 - Paginated user list
 * @returns {ErrorResponse} 401 - Unauthorized
 */
```

**GraphQL** (if applicable):
- Generate schema documentation from type definitions
- Document queries, mutations, subscriptions separately
- Include field-level descriptions and examples
- Document custom scalars, enums, and directives

### Step 5: Validate
- Verify OpenAPI spec is valid: `npx @redocly/cli lint openapi.yaml` or `npx swagger-cli validate`
- Check for undocumented endpoints (endpoints found in code but not in docs)
- Verify all `$ref` references resolve correctly
- Check example values match declared schemas
- Ensure all error responses are documented

### Step 6: Report
```
## API Documentation Report

### Endpoints Documented
| Method | Path | Auth | Tags |
|---|---|---|---|
| GET | /api/users | Bearer | Users |
| POST | /api/users | Bearer (admin) | Users |
| GET | /api/users/:id | Bearer | Users |
| PUT | /api/users/:id | Bearer (owner) | Users |
| DELETE | /api/users/:id | Bearer (admin) | Users |

### Summary
| Metric | Count |
|---|---|
| Total endpoints | N |
| Authenticated | N |
| Public | N |
| Deprecated | N |
| Schemas generated | N |

### Format: OpenAPI 3.1 / Markdown / Inline
### Output: docs/api/ (or openapi.yaml)

### Coverage
- Endpoints documented: N/N (100%)
- Schemas from types: N
- Examples included: N endpoints
- Error responses: N endpoints

### Undocumented (if any)
- POST /api/internal/webhook - no documentation found

### Follow-up
- Run `/genskills:doc-gen` to add inline documentation to route handlers
- Run `/genskills:test-generator` to add API integration tests
- Run `/genskills:security-audit` to verify auth on all endpoints
- Preview docs: `npx @redocly/cli preview-docs openapi.yaml`
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `format`: "openapi" | "markdown" | "inline" - output format
- `outputDir`: string - where to write docs (default: "docs/api")
- `baseUrl`: string - API base URL for examples (default: "http://localhost:3000")
- `includeInternal`: boolean - document internal/admin endpoints (default: false)
- `includeDeprecated`: boolean - include deprecated endpoints (default: true)
- `exampleStyle`: "realistic" | "minimal" - example data verbosity (default: "realistic")
- `groupBy`: "resource" | "tag" | "path" - how to group endpoints (default: "resource")
