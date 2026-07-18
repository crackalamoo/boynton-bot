-- Set by trigger rather than at each call site so it also covers manual
-- UPDATEs run directly against the DB, not just writes that go through the code.
ALTER TABLE training_examples ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS training_examples_set_updated_at ON training_examples;
CREATE TRIGGER training_examples_set_updated_at
    BEFORE UPDATE ON training_examples
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();
