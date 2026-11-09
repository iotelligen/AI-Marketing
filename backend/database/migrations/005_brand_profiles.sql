CREATE TABLE IF NOT EXISTS brand_profiles (
    id VARCHAR(36) PRIMARY KEY,
    workspace_slug VARCHAR(100) NOT NULL,
    brand_name VARCHAR(150) NOT NULL,
    tagline VARCHAR(200),
    accent_color VARCHAR(7) NOT NULL DEFAULT '#16C79A',
    website VARCHAR(200),
    email VARCHAR(200),
    phone VARCHAR(50),
    logo_filename VARCHAR(500),
    logo_storage_path VARCHAR(1000),
    logo_mime_type VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_brand_profiles_workspace_slug
ON brand_profiles (workspace_slug);
