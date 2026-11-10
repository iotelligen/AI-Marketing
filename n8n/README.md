# n8n publishing workflows

FastAPI owns the actual social posts. n8n only schedules and calls the API.

## Prerequisites

1. Apply migration `backend/database/migrations/006_publish.sql`
2. Rebuild FastAPI:

```bash
cd /home/dell_laptop/projects/iotelligen-platform
docker compose up -d --build fastapi
```

3. Confirm dry-run is on (default):

```bash
curl -s http://localhost:8000/publish/platforms
```

You should see `"dry_run_default": true`.

## Import the LinkedIn workflow

1. Open http://localhost:5678
2. **Workflows → Import from File**
3. Choose `n8n/workflows/publish-approved-linkedin.json`
4. Activate the workflow

The workflow calls `http://fastapi:8000` on the Docker `backend` network every hour.

## Manual dry-run test

Approve a finished video in the dashboard (VideoVersion approval), then:

```bash
# See what is ready
curl -s "http://localhost:8000/publish/ready?platforms=linkedin"

# Publish in dry-run (default)
curl -s -X POST http://localhost:8000/publish/jobs \
  -H "Content-Type: application/json" \
  -d '{"version_id":"YOUR_VERSION_ID","platforms":["linkedin"],"requested_by":"api"}'
```

A successful dry-run returns `"status":"dry_run"` and does not call LinkedIn.

## Go live on LinkedIn

1. Create a LinkedIn developer app and obtain an access token with posting scopes.
2. Register the account:

```bash
curl -s -X POST http://localhost:8000/publish/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_slug":"iotelligen-marketing",
    "platform":"linkedin",
    "display_name":"IoTelliGen LinkedIn",
    "access_token":"YOUR_TOKEN",
    "author_urn":"urn:li:organization:YOUR_ORG_ID"
  }'
```

3. Set in `.env`:

```bash
PUBLISH_DRY_RUN=false
```

4. Rebuild FastAPI again:

```bash
docker compose up -d --build fastapi
```

5. Re-run the n8n workflow (or wait for the hourly trigger).

Tokens are stored in Postgres as plain JSON for local development. Encrypt them before any non-local deployment.
