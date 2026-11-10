-- Add workspace + publish tracking for marketing text posts.
ALTER TABLE marketing_posts
    ADD COLUMN IF NOT EXISTS workspace_slug VARCHAR(100);

UPDATE marketing_posts
SET workspace_slug = 'iotelligen'
WHERE workspace_slug IS NULL OR workspace_slug = '';

ALTER TABLE marketing_posts
    ALTER COLUMN workspace_slug SET DEFAULT 'iotelligen';

ALTER TABLE marketing_posts
    ALTER COLUMN workspace_slug SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_marketing_posts_workspace_slug
ON marketing_posts (workspace_slug);

ALTER TABLE marketing_posts
    ADD COLUMN IF NOT EXISTS remote_post_id VARCHAR(200);

ALTER TABLE marketing_posts
    ADD COLUMN IF NOT EXISTS remote_url VARCHAR(1000);

ALTER TABLE marketing_posts
    ADD COLUMN IF NOT EXISTS publish_error TEXT;

ALTER TABLE marketing_posts
    ADD COLUMN IF NOT EXISTS publish_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE marketing_posts
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
