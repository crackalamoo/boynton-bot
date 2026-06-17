import asyncio
import dataclasses
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Job:
    kind: str  # "chat" | "compact"

    # chat
    user_message: str | None = None
    max_tokens: int | None = None
    sse_queue: "asyncio.Queue[str | None] | None" = None  # None for fire-and-forget (background jobs)

    # compact
    result_queue: "asyncio.Queue[tuple[Any, Exception | None]] | None" = None


class JobQueue:
    """Per-channel FIFO job queue, each drained by one long-lived asyncio task.

    `run_chat` and `run_compact` are called with (channel, job) and are responsible
    for doing the actual work and signaling any consumers (sse_queue / result_queue).
    """

    def __init__(
        self,
        run_chat: Callable[[str, Job], Awaitable[None]],
        run_compact: Callable[[str, Job], Awaitable[None]],
    ):
        self._run_chat = run_chat
        self._run_compact = run_compact
        self._lock = asyncio.Lock()
        self._queues: dict[str, "asyncio.Queue[Job]"] = {}
        self._workers: dict[str, "asyncio.Task[None]"] = {}

    async def _get_queue(self, channel: str) -> "asyncio.Queue[Job]":
        async with self._lock:
            q = self._queues.get(channel)
            if q is None:
                q = asyncio.Queue()
                self._queues[channel] = q
                self._workers[channel] = asyncio.create_task(self._worker_loop(channel, q))
            return q

    async def _worker_loop(self, channel: str, q: "asyncio.Queue[Job]") -> None:
        while True:
            job = await q.get()
            try:
                if job.kind == "chat":
                    await self._run_chat(channel, job)
                elif job.kind == "compact":
                    await self._run_compact(channel, job)
                else:
                    logger.error(f"Unknown job kind: {job.kind!r}")
            except Exception:
                logger.exception(f"Unhandled error in worker for channel {channel!r}, job kind {job.kind!r}")

    async def submit_chat(self, channel: str, user_message: str, max_tokens: int | None = None) -> "asyncio.Queue[str | None]":
        sse_queue: "asyncio.Queue[str | None]" = asyncio.Queue()
        job = Job(kind="chat", user_message=user_message, max_tokens=max_tokens, sse_queue=sse_queue)
        q = await self._get_queue(channel)
        await q.put(job)
        return sse_queue

    async def submit_background(
        self,
        channel: str,
        prompt: str,
    ) -> None:
        job = Job(kind="chat", user_message=prompt)
        q = await self._get_queue(channel)
        await q.put(job)

    async def submit_compact(self, channel: str) -> Any:
        """Enqueue a compact job and wait until it completes."""
        result_queue: "asyncio.Queue[tuple[Any, Exception | None]]" = asyncio.Queue(maxsize=1)
        job = Job(kind="compact", result_queue=result_queue)
        q = await self._get_queue(channel)
        await q.put(job)
        result, exc = await result_queue.get()
        if exc is not None:
            raise exc
        return result


async def stream_queue(q: "asyncio.Queue[str | None]") -> AsyncGenerator[str, None]:
    """SSE generator that awaits a job-specific queue until the None sentinel."""
    while True:
        item = await q.get()
        if item is None:
            return
        yield item
