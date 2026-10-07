-- Supabase PostgreSQL Schema for AI Video Production Pipeline
-- Run this in the Supabase SQL Editor if you prefer manual table provisioning

-- 1. Enable pgvector extension (Supabase supports this natively)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Articles table
CREATE TABLE IF NOT EXISTS articles (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    link VARCHAR(1000) UNIQUE NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    source VARCHAR(100) NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE,
    embedding JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc'::text, now())
);
CREATE INDEX IF NOT EXISTS idx_articles_link ON articles (link);

-- 3. Cluster Runs table
CREATE TABLE IF NOT EXISTS cluster_runs (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(64) UNIQUE NOT NULL,
    cluster_count INTEGER NOT NULL DEFAULT 0,
    article_count INTEGER NOT NULL DEFAULT 0,
    threshold FLOAT NOT NULL DEFAULT 0.82,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc'::text, now())
);
CREATE INDEX IF NOT EXISTS idx_cluster_runs_run_id ON cluster_runs (run_id);

-- 4. Story Clusters table
CREATE TABLE IF NOT EXISTS story_clusters (
    id SERIAL PRIMARY KEY,
    cluster_hash VARCHAR(64) UNIQUE NOT NULL,
    cluster_run_id VARCHAR(64) NOT NULL DEFAULT 'run_default',
    run_cluster_index INTEGER NOT NULL DEFAULT 1,
    title VARCHAR(500) NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    article_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    article_count INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc'::text, now())
);
CREATE INDEX IF NOT EXISTS idx_story_clusters_cluster_hash ON story_clusters (cluster_hash);
CREATE INDEX IF NOT EXISTS idx_story_clusters_run_id ON story_clusters (cluster_run_id);

-- 5. Scripts table
CREATE TABLE IF NOT EXISTS scripts (
    id SERIAL PRIMARY KEY,
    cluster_id INTEGER NOT NULL REFERENCES story_clusters(id) ON DELETE CASCADE,
    cluster_ids JSONB DEFAULT '[]'::jsonb,
    title VARCHAR(500) NOT NULL,
    aspect_ratio VARCHAR(20) NOT NULL DEFAULT '9:16',
    beats JSONB NOT NULL DEFAULT '[]'::jsonb,
    full_narration TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc'::text, now())
);
CREATE INDEX IF NOT EXISTS idx_scripts_cluster_id ON scripts (cluster_id);

-- 6. Render Jobs table
CREATE TABLE IF NOT EXISTS render_jobs (
    id SERIAL PRIMARY KEY,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    aspect_ratio VARCHAR(20) NOT NULL DEFAULT '9:16',
    audio_path VARCHAR(1000),
    captions_path VARCHAR(1000),
    render_props_path VARCHAR(1000),
    output_video_path VARCHAR(1000),
    duration_seconds FLOAT,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc'::text, now()),
    completed_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_render_jobs_script_id ON render_jobs (script_id);

-- 7. Cost Log table
CREATE TABLE IF NOT EXISTS cost_log (
    id SERIAL PRIMARY KEY,
    job_id INTEGER,
    stage VARCHAR(50) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100),
    units FLOAT NOT NULL DEFAULT 0.0,
    unit_type VARCHAR(30) NOT NULL,
    cost_usd FLOAT NOT NULL DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc'::text, now())
);
CREATE INDEX IF NOT EXISTS idx_cost_log_job_id ON cost_log (job_id);
CREATE INDEX IF NOT EXISTS idx_cost_log_stage ON cost_log (stage);

-- 8. Action Logs table
CREATE TABLE IF NOT EXISTS action_logs (
    id SERIAL PRIMARY KEY,
    stage VARCHAR(50) NOT NULL,
    action VARCHAR(100) NOT NULL,
    actor VARCHAR(50) NOT NULL DEFAULT 'cli',
    status VARCHAR(30) NOT NULL,
    job_id INTEGER,
    message TEXT NOT NULL DEFAULT '',
    details JSONB,
    duration_seconds FLOAT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc'::text, now())
);
CREATE INDEX IF NOT EXISTS idx_action_logs_stage ON action_logs (stage);
CREATE INDEX IF NOT EXISTS idx_action_logs_job_id ON action_logs (job_id);

-- 9. Visual Assets table
CREATE TABLE IF NOT EXISTS visual_assets (
    id SERIAL PRIMARY KEY,
    asset_hash VARCHAR(64) UNIQUE NOT NULL,
    source_url VARCHAR(1000),
    local_path VARCHAR(1000) NOT NULL,
    media_type VARCHAR(20) NOT NULL DEFAULT 'image',
    provider VARCHAR(50) NOT NULL,
    query VARCHAR(255) NOT NULL DEFAULT '',
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    emotion_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    shot_type VARCHAR(50),
    aspect_ratio VARCHAR(20) NOT NULL DEFAULT '9:16',
    vlm_score FLOAT,
    vlm_reason TEXT,
    usage_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc'::text, now()),
    last_used_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT timezone('utc'::text, now())
);
CREATE INDEX IF NOT EXISTS idx_visual_assets_asset_hash ON visual_assets (asset_hash);
CREATE INDEX IF NOT EXISTS idx_visual_assets_query ON visual_assets (query);
