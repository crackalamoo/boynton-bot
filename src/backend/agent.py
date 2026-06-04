from openai import OpenAI
from dotenv import load_dotenv
from dataclasses import dataclass, field
import json
import os

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

MODEL = os.getenv("LLM_MODEL", "gpt-5.4-mini")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
SUMMARIZATION_THRESHOLD = 100_000  # tokens (approximate)

SYSTEM_PROMPT = """You are a personal research assistant for Harys Dalvi, a software engineer focused on growing his career. \
You help him stay current with technology, learn new things, think through problems, and make progress on side projects. \
Be concise, direct, and assume strong technical knowledge."""


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


@dataclass
class Session:
    messages: list = field(default_factory=list)
    summary: str | None = None
    summary_through_idx: int = -1  # all messages up to and including this index are covered by summary


class Agent:
    def __init__(self):
        self.sessions: dict[str, Session] = {}

    def _session(self, channel: str) -> Session:
        if channel not in self.sessions:
            self.sessions[channel] = Session()
        return self.sessions[channel]

    def get_history(self, channel: str) -> list:
        return [m for m in self._session(channel).messages if m["role"] in ("user", "assistant")]

    def clear(self, channel: str):
        self.sessions[channel] = Session()

    def chat(self, channel: str, user_message: str):
        """Yields SSE-formatted strings."""
        client = _get_client()
        session = self._session(channel)

        session.messages.append({"role": "user", "content": user_message})

        # Messages not yet covered by the summary (excluding the just-added user message)
        unsummarized = session.messages[session.summary_through_idx + 1 : -1]
        did_summarize = False

        if _estimate_tokens(unsummarized) > SUMMARIZATION_THRESHOLD:
            prior = f"Prior summary:\n{session.summary}\n\n" if session.summary else ""
            lines = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in unsummarized)
            session.summary = _complete(client, [{
                "role": "user",
                "content": f"Summarize this conversation concisely, preserving key facts and context:\n\n{prior}{lines}"
            }])
            session.summary_through_idx = len(session.messages) - 2  # everything before the current user message
            did_summarize = True

        # Build context: system prompt + optional summary + messages after summary pointer
        context = [{"role": "system", "content": SYSTEM_PROMPT}]
        if session.summary:
            context.append({"role": "system", "content": f"[Summary of earlier conversation]: {session.summary}"})
        context += session.messages[session.summary_through_idx + 1:]

        accumulated = []
        try:
            stream = client.chat.completions.create(model=MODEL, messages=context, stream=True)
            for chunk in stream:
                content = chunk.choices[0].delta.content or ""
                if content:
                    accumulated.append(content)
                    yield "data: " + json.dumps({"type": "token", "content": content}) + "\n\n"
            session.messages.append({"role": "assistant", "content": "".join(accumulated)})
            yield "data: " + json.dumps({"type": "done", "summarized": did_summarize}) + "\n\n"
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "message": str(e)}) + "\n\n"
