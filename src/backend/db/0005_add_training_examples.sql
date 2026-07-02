CREATE TABLE IF NOT EXISTS training_examples (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    message_id          BIGINT NOT NULL REFERENCES messages(id),
    label               TEXT NOT NULL CHECK (label IN ('up', 'down')),
    prompt              JSONB NOT NULL,
    response            JSONB NOT NULL,
    note                TEXT,
    correction          JSONB,
    correction_status   TEXT CHECK (correction_status IN ('pending', 'drafting', 'drafted', 'approved', 'rejected', 'error')),
    UNIQUE (message_id)
);
