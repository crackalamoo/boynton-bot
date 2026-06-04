from flask import Flask, request, jsonify, Response
from dotenv import load_dotenv
from openai import OpenAI
import json
import os

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, static_folder=os.path.join(ROOT, "src/frontend/dist"), static_url_path="")

MODEL = os.getenv("LLM_MODEL", "gpt-5.4-mini")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")  # None = use OpenAI default
SUMMARIZATION_THRESHOLD = 100_000  # tokens (approximate)

SYSTEM_PROMPT = """You are a personal research assistant for Harys Dalvi, a software engineer focused on growing his career. \
You help him stay current with technology, learn new things, think through problems, and make progress on side projects. \
Be concise, direct, and assume strong technical knowledge."""

# Single global conversation history (personal tool, one user)
history = []


def get_client():
    api_key = os.getenv("OPENAI_API_KEY", "local")
    kwargs = {"api_key": api_key}
    if LLM_BASE_URL:
        kwargs["base_url"] = LLM_BASE_URL
    elif api_key == "local":
        raise ValueError("OPENAI_API_KEY not set")
    return OpenAI(**kwargs)


def estimate_tokens(messages):
    """Rough estimate: ~4 chars per token."""
    return sum(len(m.get("content", "")) // 4 for m in messages)


def complete(client, messages, **kwargs):
    """Collect a streamed completion into a single string."""
    chunks = client.chat.completions.create(model=MODEL, messages=messages, stream=True, **kwargs)
    return "".join(c.choices[0].delta.content or "" for c in chunks)


def summarize(messages_to_summarize):
    client = get_client()
    lines = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages_to_summarize)
    return complete(client, [{
        "role": "user",
        "content": f"Summarize this conversation concisely, preserving key facts and context:\n\n{lines}"
    }])


@app.route("/chat")
def index():
    return app.send_static_file("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    global history

    data = request.json
    user_message = (data or {}).get("message", "").strip()
    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    try:
        client = get_client()
    except ValueError as e:
        return jsonify({"error": str(e)}), 503

    history.append({"role": "user", "content": user_message})

    # Summarize if history (excluding the just-added message) is over threshold
    if estimate_tokens(history[:-1]) > SUMMARIZATION_THRESHOLD:
        summary_text = summarize(history[:-1])
        history = [
            {"role": "system", "content": f"[Summary of earlier conversation]: {summary_text}"},
            history[-1],  # keep the current user message
        ]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    summarized = any(
        m["role"] == "system" and "Summary of earlier" in m.get("content", "")
        for m in history
    )

    def generate():
        accumulated = []
        try:
            stream = client.chat.completions.create(model=MODEL, messages=messages, stream=True)
            for chunk in stream:
                content = chunk.choices[0].delta.content or ""
                if content:
                    accumulated.append(content)
                    yield "data: " + json.dumps({"type": "token", "content": content}) + "\n\n"
            assistant_message = "".join(accumulated)
            history.append({"role": "assistant", "content": assistant_message})
            yield "data: " + json.dumps({"type": "done", "summarized": summarized}) + "\n\n"
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "message": str(e)}) + "\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/history", methods=["GET"])
def get_history():
    return jsonify([m for m in history if m["role"] in ("user", "assistant")])


@app.route("/api/clear", methods=["POST"])
def clear():
    global history
    history = []
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9174, debug=False)

