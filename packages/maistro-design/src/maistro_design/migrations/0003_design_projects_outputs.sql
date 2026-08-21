-- Migration 0003: DesignProject and DesignOutput persistence
-- Adds tables for design project artifacts and discovery context
-- Complements canvas layer (canvases, layers) for design skill outputs

CREATE TABLE IF NOT EXISTS design_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    skill_slug TEXT NOT NULL,
    design_system_slug TEXT NOT NULL,
    org_id TEXT NOT NULL,
    team_id TEXT,
    trust_tier TEXT NOT NULL DEFAULT 't3',
    canvas_id UUID,
    discovery_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (org_id) REFERENCES orgs(id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_design_projects_org_id ON design_projects(org_id);
CREATE INDEX IF NOT EXISTS idx_design_projects_org_skill ON design_projects(org_id, skill_slug);
CREATE INDEX IF NOT EXISTS idx_design_projects_skill_slug ON design_projects(skill_slug);
CREATE INDEX IF NOT EXISTS idx_design_projects_created_at ON design_projects(created_at DESC);

CREATE TABLE IF NOT EXISTS design_outputs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL,
    format TEXT NOT NULL,
    content TEXT NOT NULL,
    url TEXT,
    trust_tier TEXT NOT NULL DEFAULT 't3',
    metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (project_id) REFERENCES design_projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_design_outputs_project_id ON design_outputs(project_id);
CREATE INDEX IF NOT EXISTS idx_design_outputs_format ON design_outputs(format);
CREATE INDEX IF NOT EXISTS idx_design_outputs_created_at ON design_outputs(created_at DESC);

-- Ensure orgs and teams tables exist (from maistro-core)
-- If running in isolation, create minimal tables for testing:
-- CREATE TABLE IF NOT EXISTS orgs (id TEXT PRIMARY KEY);
-- CREATE TABLE IF NOT EXISTS teams (id TEXT PRIMARY KEY, org_id TEXT);
