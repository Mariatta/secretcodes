# Architecture overview

!!! info "Status"
    Skeleton: app-specific detail is filled in over time. The shape below
    reflects the current stack; each section expands with specifics.

## The stack at a glance

| Concern | Technology | Where it runs |
|---|---|---|
| Web app | Django (multi-app project) | Container on Azure App Service |
| WSGI server | gunicorn | Inside the container |
| Database | PostgreSQL (Flexible Server) | Azure |
| Static & media files | django-storages + S3 backend | DigitalOcean Spaces |
| AI agent access | MCP server (`/mcp/`) | Same app/container |
| Config | Environment variables | Per-host app settings |

## Django apps

The platform is several Django apps sharing one project. Document each here as
its responsibilities settle, for example:

- `accounts/`: shared membership/invitation patterns across apps.
- `content_planner/`: blog and social campaign tracking.
- *(availability portal, meetup management, etc., add as they stabilize.)*

For each app, note: what it owns, its key models, and any cross-app contracts.

## Request & data flow

1. Request hits App Service (TLS terminated at the platform).
2. App Service routes to the container on the port set by `WEBSITES_PORT`.
3. gunicorn serves Django; the DB is reached via `DATABASE_URL` (TLS required).
4. Static/media URLs point at Spaces over the S3-compatible endpoint.

## Deliberate non-choices (to stay portable)

These Azure conveniences are **avoided on purpose**, each would couple the app
to Azure and raise the cost of leaving:

- Managed identity / Key Vault references for the DB → use a plain connection
  string in an env var.
- Oryx source builds → ship a self-built container image.
- Application Insights SDK woven into app code → monitor at the platform level.
- Azure Blob for media → media stays on Spaces (Azure Blob isn't S3-compatible).

## The portability contract (env vars)

The complete set the app reads, identical on every host:

```
DATABASE_URL              SECRET_KEY        DEBUG        DJANGO_ALLOWED_HOSTS
AWS_ACCESS_KEY_ID         AWS_SECRET_ACCESS_KEY
AWS_STORAGE_BUCKET_NAME   AWS_S3_ENDPOINT_URL
```

Moving hosts = recreate these values + point the new platform at the same image.
