# AI-Marketing — Codex Handoff

Prepared: 2026-11-09  
Repository: iotelligen/AI-Marketing  
Default branch inspected: main

## How to read this document

This handoff deliberately separates three kinds of information:

- **Verified repository facts** come from a read-only inspection of the current main branch on 2026-11-09.
- **Historical conversation decisions** came from the preceding ChatGPT conversation. They express agreed product direction, but are not proof that code exists.
- **Unverified assumptions / follow-ups** are recommendations or things that must be checked before implementation.

No application code, repository file, branch, pull request, or GitHub setting was changed while preparing this document.

## Product goal

### Historical conversation decision

Build an AI storytelling system for marketing videos. The user should supply only:

1. Topic
2. Target platform
3. Objective
4. Target audience
5. Duration

The AI should decide the narrative arc, script, visual direction, scenes, imagery, motion, pacing, transitions, and render configuration. The user should approve the completed result before anything is published.

The intended user experience is a simplified Video Studio: brief input, automatic creative production, one clear review/approval gate, then publication. The user continues to run Docker locally and validate the system.

### Verified repository facts

The current product already contains the core of a video-production workflow:

- An LLM-backed planner generates structured storyboards.
- FAL image generation creates a scene image for each storyboard scene.
- A human can approve, reject, regenerate, or delete individual images.
- Rendering is blocked until every storyboard scene has a completed, approved image.
- A Remotion service renders the approved scene images into a video.

There is no verified publishing integration, publishing API, platform credential storage, or automatic publishing worker in the inspected repository.

### Implementation update — 2026-11-09

The first autonomous-production slice is now implemented locally:

- POST /videos/productions accepts the existing video brief, generates a plan, queues all scene-image assets, and automatically submits rendering once every scene asset completes.
- Autonomous scene assets are system-approved so the only required human gate is the completed video.
- Render completion creates a video version with pending approval while keeping the existing completed job state for dashboard compatibility.
- PATCH /videos/jobs/{job_id}/versions/{version_id}/approval records an immutable final approval or rejection on the latest completed version. The job remains completed so the existing dashboard keeps the rendered video playable.
- Publishing remains intentionally unimplemented. A separate migration, 004_video_version_approval.sql, must be applied to existing databases.

### Image-to-video test path — 2026-11-09

POST /videos/assets/{asset_id}/video queues a Seedance image-to-video clip from a completed scene image. It accepts a motion_prompt and duration_seconds from 4 to 15 seconds; the initial test default is 10 seconds at 720p. The completed MP4 is stored as a VideoAsset and can be retrieved from its file_url.

When an approved scene video exists, both render paths prefer it over the source image. This allows Remotion to assemble generated AI video clips while preserving image fallback for scenes without a clip.

## Current architecture

### Verified repository facts

| Area | Current implementation | Key locations |
|---|---|---|
| API | Python FastAPI application, SQLAlchemy ORM, Pydantic models | backend/app/main.py; backend/app/routers |
| Database | PostgreSQL 17 with pgvector extension | docker-compose.yml; database/init/01-extensions.sql |
| Queues | Redis 7 is used by RQ for image generation and BullMQ for video rendering | backend/app/services/asset_service.py; backend/app/workers/asset_worker.py; video-renderer/src/server.js |
| Image generation | FAL provider, model configurable through FAL_IMAGE_MODEL | backend/app/providers/fal/image_provider.py |
| Video planning | LiteLLM produces a validated JSON video plan | backend/app/services/video_planner_service.py; backend/app/schemas/video_planner.py |
| Video rendering | Node/Express service using Remotion and BullMQ | video-renderer/src/server.js; video-renderer/src/compositions |
| Dashboard | Next.js 16 / React 19 Video Studio interface | dashboard/src/app/page.tsx; dashboard/src/components/AssetGallery.tsx |
| Documents / knowledge | Document ingestion, processing, embeddings, and workspace search endpoints | backend/app/routers/documents.py |
| Marketing posts | Separate LLM-backed marketing-post generation and revision flow | backend/app/routers/marketing.py |
| Workflow tool | n8n service is defined in Docker Compose | docker-compose.yml |
| Reverse proxy | Traefik forwards API paths to FastAPI | traefik/traefik.yml; traefik/dynamic/api.yml |

### Verified end-to-end video flow

1. The dashboard sends the video brief to POST /videos/plan.
2. The backend uses LiteLLM to produce a VideoPlan with ordered scenes, narration, on-screen text, visual prompts, transitions, animation metadata, duration, and aspect ratio.
3. POST /videos/jobs/from-plan persists the plan as a draft VideoJob.
4. POST /videos/jobs/{job_id}/assets/generate-from-plan creates one image asset task per scene.
5. RQ stores the tasks in Redis; asset-worker calls FAL and saves the resulting images under the mounted asset directory.
6. The dashboard’s asset gallery lets a person approve, reject, regenerate, or delete each image.
7. POST /videos/jobs/{job_id}/render requires every scene to have a completed and approved image. It prepares a DynamicVideo payload and submits it to the renderer.
8. The renderer queues the job in BullMQ, uses Remotion to render it, and exposes job status and the finished file.
9. FastAPI synchronizes renderer status, creates VideoVersion records for completed renders, and proxies the finished video to the dashboard.

### Architectural boundary

The dashboard is not a Docker Compose service. It is currently expected to run separately through Next.js on localhost:3000, while Compose runs the API and supporting services.

## Docker services

### Verified repository facts

| Compose service | Purpose | Network exposure / persistence |
|---|---|---|
| asset-worker | RQ worker that generates FAL image assets | Mounts ./storage/assets at /data/assets; backend network |
| video-renderer | Express, BullMQ, and Remotion renderer | Internal port 8100; video_data volume; read-only asset mount |
| n8n | Workflow automation service | Host port 127.0.0.1:5678; n8n_data volume |
| docling | Document processing service | Internal backend network |
| fastapi | Main API | Host port 127.0.0.1:8000; document and asset mounts |
| postgres | pgvector/pgvector:pg17 | postgres_data volume; health check |
| redis | Redis 7 with AOF and password | redis_data volume; health check |
| traefik | Reverse proxy | Host port 127.0.0.1:80; proxy network |

FastAPI is configured with VIDEO_RENDERER_URL=http://video-renderer:8100. The renderer’s health check calls its internal GET /health endpoint. Traefik’s dynamic API route forwards to http://fastapi:8000.

Compose references environment values including database credentials, Redis password, OpenAI API key, embedding configuration, Docling configuration, FAL key/model, and n8n credentials. An example environment file was not present in the inspected tree.

## Backend and API inventory

### Verified repository facts

FastAPI’s health endpoint is GET /health. Workspace creation and listing are POST /workspaces and GET /workspaces.

The router prefixes and routes below were extracted from the current sources.

| Area | Endpoint |
|---|---|
| Video planning | POST /videos/plan |
| Start autonomous production | POST /videos/productions |
| Video-plan revision | POST /videos/plan/revise |
| Save planned video draft | POST /videos/jobs/from-plan |
| Submit legacy/template render job | POST /videos/jobs |
| Generate all scene images from a plan | POST /videos/jobs/{job_id}/assets/generate-from-plan |
| Render approved plan | POST /videos/jobs/{job_id}/render |
| List / get video jobs | GET /videos/jobs; GET /videos/jobs/{job_id} |
| List versions / stream completed video | GET /videos/jobs/{job_id}/versions; GET /videos/jobs/{job_id}/video |
| Final-video approval | PATCH /videos/jobs/{job_id}/versions/{version_id}/approval |
| Request one image asset | POST /videos/jobs/{job_id}/assets/images |
| List job assets | GET /videos/jobs/{job_id}/assets |
| Read asset metadata or file | GET /videos/assets/{asset_id}; GET /videos/assets/{asset_id}/file |
| Regenerate, review, delete an asset | POST /videos/assets/{asset_id}/regenerate; PATCH /videos/assets/{asset_id}/review; DELETE /videos/assets/{asset_id} |
| Marketing post generation / revision | POST /marketing/posts/generate; POST /marketing/posts/{post_id}/revise |
| Marketing post versions | GET /marketing/posts/{post_id}/versions |
| Workspace document endpoints | POST /workspaces/{workspace_slug}/documents; GET /workspaces/{workspace_slug}/documents |
| Document processing / embedding | POST /workspaces/{workspace_slug}/documents/{document_id}/process; POST /workspaces/{workspace_slug}/documents/{document_id}/embed |
| Workspace search | POST /workspaces/{workspace_slug}/search |

The renderer is internal and has GET /health, POST /render, GET /jobs/:id, and GET /videos/:id.

## Video pipeline details

### Verified repository facts

VideoPlanRequest accepts topic, platform, target_audience, objective, duration_seconds, and aspect_ratio. Supported aspect ratios are 9:16, 16:9, and 1:1. The planner schema validates sequential scene numbers and requires scene durations to total the requested video duration.

The planner prompt currently directs the LLM to create an industrial video storyboard, keep every scene visually meaningful, use visual prompts that can be sent to an image or video model, create an engaging opening, and return valid structured JSON. The Video Agent configuration limits duration to 10–180 seconds and declares human approval as required.

The image worker creates image-type VideoAsset records with provider fal. The asset service defaults FAL_IMAGE_MODEL to fal-ai/flux/dev if no environment value is supplied. Asset records capture scene number, provider/model, prompt, storage path, file metadata, generation status, review status, review timestamp, and review note.

The plan-driven renderer path always creates the DynamicVideo composition. DynamicVideo currently supports image scenes, image scaling/animation metadata, on-screen text, narration metadata, and fade, dissolve, or slide transitions. Renderer validation allows 1–30 scenes, 1–60 seconds per scene, and a total duration of 1–180 seconds.

The older POST /videos/jobs path supports only template_id IndustrialPromo. The repository also has an IndustrialPromo Remotion composition. The plan-driven path is the current path that uses DynamicVideo.

## Dashboard details

### Verified repository facts

The dashboard’s main page currently:

- Collects topic, platform, target audience, objective, duration, aspect ratio, and optional creative direction.
- Generates a storyboard and exposes editable narration, visual prompts, on-screen text, and transitions per scene.
- Saves the plan as a draft job.
- Offers three explicit actions: generate scene images, review/approve assets, render approved video.
- Polls queued/submitting/rendering jobs and displays versions plus video preview.

AssetGallery supports asset filtering, image preview, approval/rejection notes, regeneration, file opening, and deletion.

This is a capable production console, but it is more manual than the agreed simplified autonomous-storytelling experience.

## Data model and state

### Verified repository facts

Relevant ORM models are Workspace, Document, DocumentChunk, MarketingPost, MarketingPostVersion, VideoJob, VideoAsset, and VideoVersion.

Observed video-job progression is draft → assets_pending / assets_ready → submitting / queued / rendering → completed. The latest VideoVersion then moves from pending approval to approved or rejected. Autonomous jobs start at assets_pending and advance automatically after every scene image completes. Exact transitions are distributed across the video router, asset worker, and renderer synchronization code.

Image assets use generation states such as pending, generating, completed, and failed. The review state is pending, approved, or rejected. Rendering rejects a plan when a scene is missing a completed, approved image.

Video versions now have approval_status, reviewed_at, and approval_note. A completed job with its latest version in pending approval is awaiting final review. The final-review API accepts approved or rejected only for that latest version.

## Required product decisions for the next implementation

### Historical conversation decisions to preserve

- Keep creative control automated: users should not be required to write scripts, choose images, design motion, or choreograph transitions.
- Use the requested platform, objective, audience, and duration as creative constraints, not as a detailed production form.
- Keep a human approval gate before publication.
- Continue using Docker locally for integration tests; the user runs those commands and observes results.

### Recommended interpretation — unverified design proposal

Replace the current multi-step asset-review workflow with this default flow:

1. User submits the five-field brief.
2. AI plans the narrative, builds the storyboard, generates assets, selects motion and transitions, and renders a draft automatically.
3. User reviews one finished video, with an optional expandable storyboard/asset audit trail.
4. User approves, requests a regenerate/revision, or declines.
5. Only an approved final version can enter a publishing workflow.

Do not remove the existing asset-level audit data. Keep it available for diagnostics, retries, and advanced review. The simplified dashboard should hide it behind an “advanced details” view rather than require it for normal use.

## Current implementation status

### Verified complete or substantially implemented

- FastAPI service, database connectivity, Docker service definitions, Redis, pgvector, Traefik, n8n, and Docling containers exist.
- Structured LLM video planning and plan revision exist.
- Video plan drafts, jobs, renderer-status synchronization, completed versions, and streaming are implemented.
- Asynchronous FAL scene-image generation via Redis/RQ exists.
- Asset review, regeneration, and deletion exist.
- Remotion-based asynchronous rendering exists.
- The Next.js dashboard implements the manual storyboard-to-render workflow.
- An autonomous production endpoint now orchestrates brief → plan → scene-image generation → render and waits for final-video approval.
- Final approval/rejection is stored against an individual VideoVersion.

### Verified absent or incomplete relative to the intended product

- Publishing to LinkedIn, Instagram, TikTok, YouTube, Facebook, or any other platform is not implemented.
- Platform account connection, credential management, scheduling, publish retries, and publish audit records are not visible in the inspected tree.
- Fully automatic orchestration from brief to rendered draft is not exposed as one backend job or one dashboard action.
- n8n is configured as a container, but no repository-managed n8n workflow export was found.
- Automated tests were not found in the current tracked file tree.
- The root README is effectively empty; dashboard README is the standard Next.js starter text.

## Known issues and risks

### Verified repository facts / direct observations

- backend/app/main.py registers the documents and marketing routers twice. This should be checked before extending routing because duplicate registrations can produce duplicate route metadata and confusing OpenAPI output.
- Database migrations 002_video_assets.sql, 003_video_asset_review.sql, and 004_video_version_approval.sql exist under backend/database/migrations, but Docker Compose mounts only database/init into PostgreSQL’s initialization directory. No migration runner was found in the Compose configuration. Existing databases may therefore lack the review columns unless migrations were applied manually.
- Base.metadata.create_all runs at API import time. That creates missing ORM tables but is not a replacement for migration management.
- The dashboard is outside Compose, while API CORS is limited to localhost:3000 and 127.0.0.1:3000. This is compatible with local Next.js development but must be revisited for deployment.
- The video renderer uses a separate named video_data volume, while assets are a host-mounted directory shared read-only with the renderer. FastAPI retrieves final output by proxying the renderer instead of reading that volume directly.
- The repository currently tracks Python __pycache__ files and a 2.1 MB video-1.mp4 binary. These are likely repository hygiene concerns.
- The service timezone in Compose is Europe/Oslo for n8n and the renderer, not necessarily the deployment/operator timezone.
- No authentication or authorization dependency is visible in the inspected FastAPI entry point and the video/asset routes. Treat all write routes as local-development-only until an auth model is designed and verified.
- Docker images use n8nio/n8n:latest and several package dependencies are tightly pinned. Reproducibility and update policy need attention.

### Historical conversation notes

The previous conversation reported that ChatGPT’s GitHub access was read-only. The current connector check independently confirms read access only.

### Unverified assumptions to validate before implementation

- Whether the current database already has every migration applied.
- Whether a valid environment file and required OpenAI/FAL/n8n credentials are available locally.
- Whether FAL’s configured model supports all intended aspect ratios and commercial-use requirements.
- Whether the planned publishing channels, brand rules, moderation requirements, and legal review requirements have been selected.
- Whether n8n is intended to remain in the architecture or should be replaced by application-managed orchestration.

## Development priorities

1. **Create one autonomous production job.** Accept only the five-field brief, persist an immutable creative brief, and orchestrate plan → asset generation → quality checks → render as a resumable background workflow.
2. **Add final-video approval and publishing states.** Model draft_rendered, awaiting_final_approval, approved_for_publish, publishing, published, publish_failed, and cancelled. Final approval must attach to a specific VideoVersion, not merely to a mutable VideoJob.
3. **Build publishing adapters deliberately.** Add one platform at a time, store account connections securely, make posting idempotent, record remote IDs/URLs, and provide retry and audit records. Never infer that approved means automatically publish unless the user explicitly chooses that policy.
4. **Simplify the dashboard.** Make brief submission and final review the normal path. Retain storyboard and per-asset controls behind advanced details.
5. **Harden orchestration.** Define idempotency keys, job locks, retry limits, timeouts, provider error handling, progress events, and safe cancellation across RQ and BullMQ.
6. **Establish database migrations.** Adopt one migration mechanism, make it run predictably in local and deployed environments, and remove reliance on import-time table creation for schema evolution.
7. **Add tests and documentation.** Begin with planner-schema validation, approval gates, asset-path safety, job-state transitions, renderer payload validation, and one Docker-backed end-to-end smoke test.
8. **Address baseline hygiene.** Fix duplicate router registration, add a useful root README and env template, decide policy for generated/binary files, pin images intentionally, and add authentication before non-local exposure.

## Local testing workflow

### Historical conversation decision

The user runs Docker locally and verifies the results. Codex should prepare focused changes, explain the expected verification, and not assume it can operate the user’s local Docker environment.

### Verified starting points

Compose exposes FastAPI on localhost:8000, Traefik on localhost:80, and n8n on localhost:5678. The dashboard README directs developers to run its Next.js server on localhost:3000.

### Recommended verification sequence — run by the user

1. Create or confirm the local environment configuration required by docker-compose.yml, including PostgreSQL, Redis, OpenAI, FAL, Docling, and n8n values.
2. Build and start the Compose stack with Docker Compose.
3. Confirm API health through GET http://localhost:8000/health and inspect health/status for PostgreSQL, Redis, asset-worker, and video-renderer.
4. Start the dashboard from the dashboard directory using its documented Next.js development command.
5. Submit a short, low-cost video brief through the dashboard.
6. Verify that a valid plan is returned and saved as a draft.
7. Generate scene assets and inspect worker logs / asset statuses. Approve all completed images.
8. Submit rendering, confirm renderer progress, and confirm that the dashboard plays the completed video through the FastAPI endpoint.
9. For any new automation work, verify both the happy path and provider failure/retry behavior without publishing externally.

Before a production workflow is considered ready, add and run automated tests for the state transitions above. There is no verified current CI/test workflow to rely on.

## GitHub access status

### Verified repository facts

- Repository: iotelligen/AI-Marketing
- Visibility: public
- Default branch: main
- Current connector permission: pull/read = enabled; push, maintain, and admin = disabled
- Current connector cannot create branches, commit changes, push, or open pull requests.

No GitHub write action was attempted for this handoff. To have Codex modify the remote repository directly, connect a GitHub integration with repository write permission; admin permission is not required for normal branch-and-pull-request work.

## High-value files for the next Codex session

| Purpose | Paths |
|---|---|
| Composition and services | docker-compose.yml; traefik/traefik.yml; traefik/dynamic/api.yml |
| API entry point | backend/app/main.py |
| Video API and lifecycle | backend/app/routers/videos.py; backend/app/schemas/video_planner.py; backend/app/services/video_planner_service.py; backend/app/services/production_service.py |
| Asset generation/review | backend/app/routers/asset_generation.py; backend/app/services/asset_service.py; backend/app/workers/asset_worker.py; backend/app/providers/fal/image_provider.py |
| Data models/migrations | backend/app/models/video_job.py; backend/app/models/video_asset.py; backend/app/models/video_version.py; backend/database/migrations/004_video_version_approval.sql |
| Renderer | video-renderer/src/server.js; video-renderer/src/compositions/DynamicVideo.tsx; video-renderer/src/compositions/IndustrialPromo.tsx; video-renderer/src/compositions/Root.tsx |
| Dashboard | dashboard/src/app/page.tsx; dashboard/src/components/AssetGallery.tsx; dashboard/package.json |
| Agent and brand guidance | backend/app/agents/video/agent.json; backend/app/agents/marketing/agent.json; backend/app/skills/marketing; brand-guidelines/skill.md |

## Suggested opening prompt for the next Codex task

Read CODEX_HANDOFF.md first. Work only on the AI-Marketing repository. Preserve the product direction: the user submits topic, platform, objective, audience, and duration; the system autonomously decides storytelling and creative execution; a human approves the final video before publishing. Start by inspecting the current branch and propose a focused implementation for a single autonomous production job with a final-video approval state. Do not publish to external platforms or change GitHub unless explicitly authorized.
