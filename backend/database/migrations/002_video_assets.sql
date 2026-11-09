
BEGIN;

ALTER TABLE video_assets
    ADD COLUMN IF NOT EXISTS scene_number INTEGER,
    ADD COLUMN IF NOT EXISTS provider VARCHAR(50),
    ADD COLUMN IF NOT EXISTS model VARCHAR(150),
    ADD COLUMN IF NOT EXISTS status VARCHAR(30)
        NOT NULL DEFAULT 'completed',
    ADD COLUMN IF NOT EXISTS prompt TEXT,
    ADD COLUMN IF NOT EXISTS mime_type VARCHAR(100),
    ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Existing assets are considered completed.
-- New ORM-created assets use the Python default "pending".
ALTER TABLE video_assets
    ALTER COLUMN status SET DEFAULT 'pending';

CREATE INDEX IF NOT EXISTS ix_video_assets_job_scene
    ON video_assets (job_id, scene_number);

CREATE INDEX IF NOT EXISTS ix_video_assets_status
    ON video_assets (status);

COMMIT;
