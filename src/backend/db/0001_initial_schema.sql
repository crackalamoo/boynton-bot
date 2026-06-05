CREATE TABLE sessions (
    id                  TEXT PRIMARY KEY,
    type                TEXT NOT NULL,
    summary             TEXT,
    summary_created_at  TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
