ALTER TABLE video_assets
ADD COLUMN IF NOT EXISTS review_status VARCHAR(30)
    NOT NULL DEFAULT 'pending';

ALTER TABLE video_assets
ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

ALTER TABLE video_assets
ADD COLUMN IF NOT EXISTS review_note TEXT;

CREATE INDEX IF NOT EXISTS ix_video_assets_review_status
ON video_assets (review_status);
