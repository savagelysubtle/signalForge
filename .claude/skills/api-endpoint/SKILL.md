---
name: api-endpoint
description: >
  Scaffold FastAPI route handlers in SignalForge. Use when adding new API endpoints,
  creating new routers, or modifying existing routes in src/backend/api/. Covers auth
  dependency injection, request/response models, rate limiting, and router wiring.
---

# API Endpoint

## File Locations

| Concern      | Path                              |
|--------------|-----------------------------------|
| Routers      | `src/backend/api/{resource}.py`   |
| Entry point  | `src/backend/main.py`             |
| Auth         | `src/backend/middleware/auth.py`   |
| Auth export  | `src/backend/middleware/__init__.py` |

## Adding a New Endpoint

### 1. Define request/response models

Place in the router file or `schemas.py` depending on scope:

```python
from pydantic import BaseModel

class MyRequest(BaseModel):
    field: str

class MyResponse(BaseModel):
    result: str
```

### 2. Create the route handler

```python
from fastapi import APIRouter, HTTPException
from middleware import CurrentUser

router = APIRouter(prefix="/my-resource", tags=["my-resource"])

@router.get("/", response_model=list[MyResponse])
async def list_items(user_id: CurrentUser) -> list[MyResponse]:
    """List items for the authenticated user."""
    client = await get_db()
    response = await client.table("items").select("*").eq("user_id", user_id).execute()
    return [MyResponse(**row) for row in response.data]

@router.post("/", status_code=201, response_model=MyResponse)
async def create_item(body: MyRequest, user_id: CurrentUser) -> MyResponse:
    """Create a new item."""
    ...
```

### 3. Wire the router in `main.py`

```python
from api.my_resource import router as my_resource_router
app.include_router(my_resource_router, prefix="/api")
```

## Auth Pattern

- `CurrentUser` is a type alias: `Annotated[str, Depends(get_current_user)]`
- Returns the `user_id` string extracted from the JWT
- Add `user_id: CurrentUser` to any route that needs auth
- Omit it for public routes (only `/health` and `/api/strategies/templates`)

## Rate Limiting

```python
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)

@router.post("/expensive-op")
@limiter.limit("5/minute")
async def expensive(request: Request, user_id: CurrentUser):
    ...
```

## Existing Routes

| Router       | Prefix         | Routes                                    |
|--------------|----------------|-------------------------------------------|
| `pipeline`   | `/api/pipeline`| POST /run, GET /status/{id}, GET /runs, GET /runs/{id} |
| `strategies` | `/api/strategies` | GET /, GET /templates, GET /{id}, POST / |
| `settings`   | `/api/settings`| GET /api-keys/status                      |
| `charts`     | `/api/charts`  | (deprecated, no routes)                   |

## Frontend API Client

After adding a backend route, add the corresponding function in `src/frontend/src/api/client.ts`:

```typescript
export async function myEndpoint(): Promise<MyType> {
  return request<MyType>("/api/my-resource");
}
```
