from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from backend.agent import Agent
from backend.heartbeat import start_heartbeat
from backend.settings_api import router as settings_router
import os
import uvicorn

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "src/frontend/dist")


@asynccontextmanager
async def lifespan(app: FastAPI):
    agent = Agent()
    start_heartbeat(agent)
    app.state.agent = agent
    yield


app = FastAPI(lifespan=lifespan)

app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")
app.include_router(settings_router)


class ChatRequest(BaseModel):
    message: str = ""


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request):
    agent = request.app.state.agent
    user_message = body.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="No message provided")
    try:
        started = agent.submit("web", user_message)
        if not started:
            raise HTTPException(status_code=409, detail="Already processing")
        return StreamingResponse(
            agent.stream("web"),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/history")
async def get_history(request: Request, include_hidden: bool = False):
    agent = request.app.state.agent
    return agent.get_history("web", include_hidden)


@app.post("/api/clear")
async def clear(request: Request):
    agent = request.app.state.agent
    agent.clear("web")
    return {"ok": True}


@app.post("/api/compact")
async def compact(request: Request):
    agent = request.app.state.agent
    did_compact = agent.compact("web")
    return {"ok": True, "compacted": did_compact}


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    return FileResponse(os.path.join(DIST, "index.html"))


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=9174)
