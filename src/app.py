from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from backend.agent import Agent
from backend.cron import start_cron
from backend.database import pool
from backend.settings_api import router as settings_router
import asyncio
import os
import uvicorn

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "src/frontend/dist")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ = await pool.open()
    agent = Agent()
    cron_task = start_cron(agent)
    app.state.agent = agent
    app.state.cron_task = cron_task
    try:
        yield
    finally:
        _ = cron_task.cancel()
        try:
            await cron_task
        except asyncio.CancelledError:
            pass
        await pool.close()


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
    sse_queue = await agent.submit_chat("web", user_message)
    return StreamingResponse(
        agent.stream_queue(sse_queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/history")
async def get_history(request: Request, include_hidden: bool = False):
    agent = request.app.state.agent
    return await agent.get_history("web", include_hidden)


@app.post("/api/clear")
async def clear(request: Request):
    agent = request.app.state.agent
    await agent.clear("web")
    return {"ok": True}


@app.post("/api/compact")
async def compact(request: Request):
    agent = request.app.state.agent
    try:
        did_compact = await agent.submit_compact("web")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "compacted": did_compact}


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    return FileResponse(os.path.join(DIST, "index.html"))


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=9174)
