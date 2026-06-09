from flask import Flask, request, jsonify, Response
from dotenv import load_dotenv
from backend.agent import Agent
from backend.heartbeat import start_heartbeat
import os

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, static_folder=os.path.join(ROOT, "src/frontend/dist"), static_url_path="")

agent = Agent()
start_heartbeat(agent)


@app.route("/chat")
def index():
    return app.send_static_file("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = (data or {}).get("message", "").strip()
    if not user_message:
        return jsonify({"error": "No message provided"}), 400
    try:
        started = agent.submit("web", user_message)
        if not started:
            return jsonify({"error": "Already processing"}), 409
        return Response(
            agent.stream("web"),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/history", methods=["GET"])
def get_history():
    data = agent.get_history("web")
    return jsonify(data)


@app.route("/api/clear", methods=["POST"])
def clear():
    agent.clear("web")
    return jsonify({"ok": True})


@app.route("/api/compact", methods=["POST"])
def compact():
    did_compact = agent.compact("web")
    return jsonify({"ok": True, "compacted": did_compact})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9174, debug=False)
