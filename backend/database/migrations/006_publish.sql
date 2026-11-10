CREATE TABLE IF NOT EXISTS publish_accounts (
    id VARCHAR(36) PRIMARY KEY,
    workspace_slug VARCHAR(100) NOT NULL,
    platform VARCHAR(50) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    credentials JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_publish_accounts_workspace_slug
ON publish_accounts (workspace_slug);

CREATE INDEX IF NOT EXISTS ix_publish_accounts_workspace_platform
ON publish_accounts (workspace_slug, platform);

CREATE TABLE IF NOT EXISTS publish_jobs (
    id VARCHAR(36) PRIMARY KEY,
    version_id VARCHAR(36) NOT NULL REFERENCES video_versions(id) ON DELETE CASCADE,
    video_job_id VARCHAR(36) NOT NULL REFERENCES video_jobs(id) ON DELETE CASCADE,
    workspace_slug VARCHAR(100) NOT NULL,
    platform VARCHAR(50) NOT NULL,
    account_id VARCHAR(36) REFERENCES publish_accounts(id) ON DELETE SET NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'queued',
    caption TEXT NOT NULL DEFAULT '',
    idempotency_key VARCHAR(200) NOT NULL,
    remote_post_id VARCHAR(200),
    remote_url VARCHAR(1000),
    error_message TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    requested_by VARCHAR(50) NOT NULL DEFAULT 'api',
    result_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    published_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_publish_jobs_idempotency_key
ON publish_jobs (idempotency_key);

CREATE INDEX IF NOT EXISTS ix_publish_jobs_version_id
ON publish_jobs (version_id);

CREATE INDEX IF NOT EXISTS ix_publish_jobs_video_job_id
ON publish_jobs (video_job_id);

CREATE INDEX IF NOT EXISTS ix_publish_jobs_workspace_slug
ON publish_jobs (workspace_slug);

CREATE INDEX IF NOT EXISTS ix_publish_jobs_status
ON publish_jobs (status);

CREATE INDEX IF NOT EXISTS ix_publish_jobs_version_platform
ON publish_jobs (version_id, platform);
