-- Tracks which model actually generated a given row (nullable — only meaningful for
-- LLM-generated rows: 'assistant' and 'tool_call'). Needed so feedback/training-data
-- collection can be restricted to rows produced by the primary (local) model — a
-- fallback-model row must never be mistaken for a primary-model one.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS model TEXT;
