from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from psycopg.rows import dict_row
from dotenv import load_dotenv
from backend.agent import Agent
from backend.cron import start_cron
from backend.database import pool
from backend.settings_api import router as settings_router
from backend.tools.cron_tools import execute_add_cron_job, execute_remove_cron_job
from typing import Any
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
async def get_history(request: Request, include_hidden: bool = False, before_id: int | None = None, limit: int = 20):
    agent = request.app.state.agent
    return await agent.get_history("web", include_hidden, before_id=before_id, limit=limit)


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


class FeedbackCreate(BaseModel):
    message_id: int
    label: str  # "up" | "down"


class FeedbackNote(BaseModel):
    note: str


class FeedbackResolve(BaseModel):
    action: str  # "approve" | "reject"
    correction: list[dict[str, Any]] | None = None


@app.post("/api/feedback")
async def create_feedback(body: FeedbackCreate, request: Request):
    if body.label not in ("up", "down"):
        raise HTTPException(status_code=400, detail="label must be 'up' or 'down'")
    agent = request.app.state.agent
    try:
        return await agent.record_feedback(body.message_id, body.label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/feedback")
async def list_feedback(request: Request):
    agent = request.app.state.agent
    return await agent.list_feedback()


@app.get("/api/feedback/message/{message_id}")
async def get_feedback_for_message(message_id: int, request: Request):
    agent = request.app.state.agent
    return await agent.get_feedback_for_message(message_id)


@app.get("/api/feedback/{example_id}")
async def get_feedback(example_id: int, request: Request):
    agent = request.app.state.agent
    row = await agent.get_feedback(example_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such feedback")
    return row


@app.post("/api/feedback/{example_id}/note")
async def add_feedback_note(example_id: int, body: FeedbackNote, request: Request):
    agent = request.app.state.agent
    try:
        return await agent.add_feedback_note(example_id, body.note)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/feedback/{example_id}/resolve")
async def resolve_feedback(example_id: int, body: FeedbackResolve, request: Request):
    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")
    agent = request.app.state.agent
    try:
        return await agent.resolve_feedback(example_id, body.action, body.correction)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class CronJobCreate(BaseModel):
    name: str
    channel: str
    prompt: str
    schedule_type: str
    schedule_value: str


class CronJobUpdate(BaseModel):
    name: str | None = None
    channel: str | None = None
    prompt: str | None = None
    schedule_type: str | None = None
    schedule_value: str | None = None
    enabled: bool | None = None


@app.get("/api/cron-jobs")
async def list_cron_jobs():
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM cron_jobs ORDER BY id ASC")
            jobs = await cur.fetchall()
    return jobs


@app.post("/api/cron-jobs")
async def create_cron_job(body: CronJobCreate):
    result = await execute_add_cron_job(
        body.name, body.channel, body.prompt, body.schedule_type, body.schedule_value
    )
    if result.startswith("Error:"):
        raise HTTPException(status_code=400, detail=result[len("Error: "):])
    return {"ok": True}


@app.patch("/api/cron-jobs/{job_id}")
async def update_cron_job(job_id: int, body: CronJobUpdate):
    from croniter import croniter
    from backend.tools.cron_tools import _parse_at

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    schedule_type = updates.get("schedule_type")
    schedule_value = updates.get("schedule_value")
    if schedule_type == "cron" and schedule_value:
        try:
            croniter(schedule_value)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid cron expression: {e}")
    elif schedule_type == "at" and schedule_value:
        try:
            _parse_at(schedule_value)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"invalid timestamp: {e}")

    cols = ", ".join(f"{k} = %s" for k in updates)
    vals = list(updates.values()) + [job_id]
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"UPDATE cron_jobs SET {cols} WHERE id = %s RETURNING id",
                vals,
            )
            row = await cur.fetchone()
            await conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no cron job with id {job_id}")
    return {"ok": True}


@app.delete("/api/cron-jobs/{job_id}")
async def delete_cron_job(job_id: int):
    result = await execute_remove_cron_job(job_id)
    if result.startswith("Error:"):
        raise HTTPException(status_code=404, detail=result[len("Error: "):])
    return {"ok": True}


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    return FileResponse(os.path.join(DIST, "index.html"))


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=9174)
