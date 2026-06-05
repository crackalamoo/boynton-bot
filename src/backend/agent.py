from openai import OpenAI
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from backend.tools.registry import TOOLS, execute_tool
from backend.memory import load_soul, load_memory_index
import json
import os

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

MODEL = os.getenv("LLM_MODEL", "gpt-5.4-mini")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
DB_URL = os.getenv("DATABASE_URL", "postgresql:///boynton_bot")
MEMORY_DIR = os.environ["MEMORY_DIR"]  # required — filesystem path to memory files
SUMMARIZATION_THRESHOLD = 100_000  # tokens (approximate)

SYSTEM_PROMPT = "You are a personal AI assistant."

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


def _stream_round(client, messages, tools=None):
    """Stream one completion round.

    Yields ("token", str) for each text delta as it arrives, then a single
    ("finish", (content, tool_calls, finish_reason)) at the end.
    """
    kwargs = dict(model=MODEL, messages=messages, stream=True)
    if tools:
        kwargs["tools"] = tools
    accumulated_content = ""
    accumulated_tool_calls: dict = {}
    finish_reason = "stop"
    for chunk in client.chat.completions.create(**kwargs):
        choice = chunk.choices[0]
        if choice.finish_reason:
            finish_reason = choice.finish_reason
        delta = choice.delta
        if delta.content:
            accumulated_content += delta.content
            yield ("token", delta.content)
        if delta.tool_calls:
            for tc in delta.tool_calls:
                i = tc.index
                if i not in accumulated_tool_calls:
                    accumulated_tool_calls[i] = {"id": "", "name": "", "arguments": ""}
                if tc.id:
                    accumulated_tool_calls[i]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        accumulated_tool_calls[i]["name"] = tc.function.name
                    if tc.function.arguments:
                        accumulated_tool_calls[i]["arguments"] += tc.function.arguments
    tool_calls = [accumulated_tool_calls[i] for i in sorted(accumulated_tool_calls)]
    yield ("finish", (accumulated_content, tool_calls, finish_reason))


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
                    "SELECT role, content, tool_name, arguments, created_at FROM messages WHERE session_id = %s ORDER BY created_at ASC",
                    (channel,)
                )
                rows = cur.fetchall()

                messages = [
                    {
                        "role": r["role"],
                        "content": r["content"],
                        "tool_name": r["tool_name"],
                        "arguments": r["arguments"],
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
                           WHERE session_id = %s AND created_at > %s AND role IN ('user', 'assistant')
                           ORDER BY created_at ASC""",
                        (channel, session["summary_created_at"])
                    )
                else:
                    cur.execute(
                        "SELECT role, content FROM messages WHERE session_id = %s AND role IN ('user', 'assistant') ORDER BY created_at ASC",
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
                           WHERE session_id = %s AND created_at > %s AND role IN ('user', 'assistant')
                           ORDER BY created_at ASC""",
                        (channel, session["summary_created_at"])
                    )
                else:
                    cur.execute(
                        "SELECT role, content FROM messages WHERE session_id = %s AND role IN ('user', 'assistant') ORDER BY created_at ASC",
                        (channel,)
                    )
                recent = cur.fetchall()

                context = [{"role": "system", "content": SYSTEM_PROMPT}]
                soul = load_soul()
                if soul:
                    context.append({"role": "system", "content": soul})
                memory_index = load_memory_index()
                if memory_index:
                    context.append({"role": "system", "content": f"[Memory index]\n{memory_index}"})
                if session["summary"]:
                    context.append({"role": "system", "content": f"[Summary of earlier conversation]: {session['summary']}"})
                # Merge consecutive assistant rows (from multi-round tool calls) into one message
                context_messages = []
                for m in recent:
                    if m["role"] == "assistant" and context_messages and context_messages[-1]["role"] == "assistant":
                        context_messages[-1] = {"role": "assistant", "content": context_messages[-1]["content"] + (m["content"] or "")}
                    else:
                        context_messages.append({"role": m["role"], "content": m["content"] or ""})
                context += context_messages
                try:
                    tool_context = list(context)
                    round_content = []
                    while True:
                        round_content = []
                        tool_calls = []
                        finish_reason = "stop"
                        for kind, value in _stream_round(client, tool_context, tools=TOOLS):
                            if kind == "token":
                                round_content.append(value)
                                yield "data: " + json.dumps({"type": "token", "content": value}) + "\n\n"
                            else:
                                _, tool_calls, finish_reason = value

                        if finish_reason == "tool_calls" and tool_calls:
                            # Save pre-tool text before inserting tool rows so DB order matches display order
                            if round_content:
                                cur.execute(
                                    "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
                                    (channel, "assistant", "".join(round_content))
                                )
                            assistant_msg: dict = {"role": "assistant", "content": "".join(round_content)}
                            assistant_msg["tool_calls"] = [
                                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                                for tc in tool_calls
                            ]
                            tool_context.append(assistant_msg)
                            for tc in tool_calls:
                                args = json.loads(tc["arguments"] or "{}")
                                yield "data: " + json.dumps({"type": "tool_call", "name": tc["name"], "arguments": args}) + "\n\n"
                                cur.execute(
                                    "INSERT INTO messages (session_id, role, tool_name, arguments) VALUES (%s, %s, %s, %s::jsonb)",
                                    (channel, "tool_call", tc["name"], tc["arguments"] or "{}")
                                )
                                result = execute_tool(tc["name"], args)
                                yield "data: " + json.dumps({"type": "tool_result", "content": result}) + "\n\n"
                                cur.execute(
                                    "INSERT INTO messages (session_id, role, tool_name, content) VALUES (%s, %s, %s, %s)",
                                    (channel, "tool_result", tc["name"], result)
                                )
                                conn.commit()
                                tool_context.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                        else:
                            break

                    if round_content:
                        cur.execute(
                            "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
                            (channel, "assistant", "".join(round_content))
                        )
                    conn.commit()
                    yield "data: " + json.dumps({"type": "done", "summarized": did_summarize}) + "\n\n"
                except Exception as e:
                    yield "data: " + json.dumps({"type": "error", "message": str(e)}) + "\n\n"

