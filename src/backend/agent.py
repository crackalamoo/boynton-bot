from openai import OpenAI
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
import json
import os

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

MODEL = os.getenv("LLM_MODEL", "gpt-5.4-mini")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
DB_URL = os.getenv("DATABASE_URL", "postgresql:///boynton_bot")
SUMMARIZATION_THRESHOLD = 100_000  # tokens (approximate)

SYSTEM_PROMPT = """You are a personal research assistant for Harys Dalvi, a software engineer focused on growing his career. \
You help him stay current with technology, learn new things, think through problems, and make progress on side projects. \
Be concise, direct, and assume strong technical knowledge."""

pool = ConnectionPool(DB_URL, open=True)


def _get_client():
    api_key = os.getenv("OPENAI_API_KEY", "local")
    kwargs = {"api_key": api_key}
    if LLM_BASE_URL:
        kwargs["base_url"] = LLM_BASE_URL
    elif api_key == "local":
        raise ValueError("OPENAI_API_KEY not set")
    return OpenAI(**kwargs)


def _estimate_tokens(messages):
    return sum(len(m.get("content", "")) // 4 for m in messages)


def _complete(client, messages):
    chunks = client.chat.completions.create(model=MODEL, messages=messages, stream=True)
    return "".join(c.choices[0].delta.content or "" for c in chunks)


class Agent:
    def get_history(self, channel: str) -> dict:
        with pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT summary_created_at FROM sessions WHERE id = %s", (channel,))
                session = cur.fetchone()
                if session is None:
                    return {"messages": [], "summary_created_at": None}

                summary_created_at = session["summary_created_at"]

                cur.execute(
                    "SELECT role, content, created_at FROM messages WHERE session_id = %s ORDER BY created_at ASC",
                    (channel,)
                )
                rows = cur.fetchall()

                messages = [
                    {
                        "role": r["role"],
                        "content": r["content"],
                        "created_at": r["created_at"].isoformat(),
                    }
                    for r in rows
                ]

                return {
                    "messages": messages,
                    "summary_created_at": summary_created_at.isoformat() if summary_created_at else None,
                }

    def clear(self, channel: str):
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM messages WHERE session_id = %s", (channel,))
                cur.execute(
                    "UPDATE sessions SET summary = NULL, summary_created_at = NULL WHERE id = %s",
                    (channel,)
                )

    def chat(self, channel: str, user_message: str):
        """Yields SSE-formatted strings."""
        client = _get_client()

        with pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Ensure session exists
                cur.execute(
                    "INSERT INTO sessions (id, type) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (channel, channel)
                )

                # Insert user message
                cur.execute(
                    "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
                    (channel, "user", user_message)
                )
                conn.commit()

                # Get session for summary info
                cur.execute("SELECT * FROM sessions WHERE id = %s", (channel,))
                session = cur.fetchone()

                # Get messages not yet covered by the summary, excluding the just-inserted user message
                if session["summary_created_at"]:
                    cur.execute(
                        """SELECT role, content FROM messages
                           WHERE session_id = %s AND created_at > %s
                           ORDER BY created_at ASC""",
                        (channel, session["summary_created_at"])
                    )
                else:
                    cur.execute(
                        "SELECT role, content FROM messages WHERE session_id = %s ORDER BY created_at ASC",
                        (channel,)
                    )
                unsummarized = cur.fetchall()[:-1]  # exclude just-inserted user message

                did_summarize = False
                if _estimate_tokens(unsummarized) > SUMMARIZATION_THRESHOLD:
                    prior = f"Prior summary:\n{session['summary']}\n\n" if session["summary"] else ""
                    lines = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in unsummarized)
                    new_summary = _complete(client, [{
                        "role": "user",
                        "content": f"Summarize this conversation concisely, preserving key facts and context:\n\n{prior}{lines}"
                    }])
                    cur.execute(
                        "UPDATE sessions SET summary = %s, summary_created_at = now() WHERE id = %s",
                        (new_summary, channel)
                    )
                    conn.commit()
                    cur.execute("SELECT * FROM sessions WHERE id = %s", (channel,))
                    session = cur.fetchone()
                    did_summarize = True

                # Build context: system prompt + optional summary + messages after summary cutoff
                if session["summary_created_at"]:
                    cur.execute(
                        """SELECT role, content FROM messages
                           WHERE session_id = %s AND created_at > %s
                           ORDER BY created_at ASC""",
                        (channel, session["summary_created_at"])
                    )
                else:
                    cur.execute(
                        "SELECT role, content FROM messages WHERE session_id = %s ORDER BY created_at ASC",
                        (channel,)
                    )
                recent = cur.fetchall()

                context = [{"role": "system", "content": SYSTEM_PROMPT}]
                if session["summary"]:
                    context.append({"role": "system", "content": f"[Summary of earlier conversation]: {session['summary']}"})
                context += [{"role": m["role"], "content": m["content"]} for m in recent]

                accumulated = []
                try:
                    stream = client.chat.completions.create(model=MODEL, messages=context, stream=True)
                    for chunk in stream:
                        content = chunk.choices[0].delta.content or ""
                        if content:
                            accumulated.append(content)
                            yield "data: " + json.dumps({"type": "token", "content": content}) + "\n\n"
                    cur.execute(
                        "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
                        (channel, "assistant", "".join(accumulated))
                    )
                    conn.commit()
                    yield "data: " + json.dumps({"type": "done", "summarized": did_summarize}) + "\n\n"
                except Exception as e:
                    yield "data: " + json.dumps({"type": "error", "message": str(e)}) + "\n\n"
