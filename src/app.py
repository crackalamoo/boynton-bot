from flask import Flask, request, jsonify, Response
from dotenv import load_dotenv
from backend.agent import Agent
import os

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, static_folder=os.path.join(ROOT, "src/frontend/dist"), static_url_path="")

agent = Agent()


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
        return Response(
            agent.chat("web", user_message),
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9174, debug=False)
