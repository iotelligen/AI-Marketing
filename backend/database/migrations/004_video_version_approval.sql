ALTER TABLE video_versions
ADD COLUMN IF NOT EXISTS approval_status VARCHAR(30)
    NOT NULL DEFAULT 'pending';

ALTER TABLE video_versions
ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

ALTER TABLE video_versions
ADD COLUMN IF NOT EXISTS approval_note TEXT;

CREATE INDEX IF NOT EXISTS ix_video_versions_approval_status
ON video_versions (approval_status);
