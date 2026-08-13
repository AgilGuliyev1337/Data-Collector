-- Migration 0003: Internet provenance tracking
-- Adds columns to store source URLs, evidence text, and confidence scores
-- for data points retrieved from internet search sources.

ALTER TABLE facts ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS evidence TEXT;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS confidence REAL CHECK (confidence >= 0 AND confidence <= 1);

COMMENT ON COLUMN facts.source_url IS 'URL of the web page where this fact was found (for internet-sourced data)';
COMMENT ON COLUMN facts.evidence IS 'Short snippet or context from the source page';
COMMENT ON COLUMN facts.confidence IS 'Estimated confidence level for this data point (0.0-1.0)';
