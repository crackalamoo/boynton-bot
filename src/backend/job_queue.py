import dataclasses
import logging
import queue
import threading
from typing import Any, Callable, Generator

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Job:
    kind: str  # "chat" | "compact"

    # chat
    user_message: str | None = None
    max_tokens: int | None = None
    sse_queue: "queue.Queue[str | None] | None" = None  # None for fire-and-forget (background jobs)

    # compact
    result_queue: "queue.Queue[tuple[Any, Exception | None]] | None" = None


class JobQueue:
    """Per-channel FIFO job queue, each drained by one long-lived daemon worker thread.

    `run_chat` and `run_compact` are called with (channel, job) and are responsible
    for doing the actual work and signaling any consumers (sse_queue / result_queue).
    """

    def __init__(self, run_chat: Callable[[str, Job], None], run_compact: Callable[[str, Job], None]):
        self._run_chat = run_chat
        self._run_compact = run_compact
        self._lock = threading.Lock()
        self._queues: dict[str, "queue.Queue[Job]"] = {}

    def _get_queue(self, channel: str) -> "queue.Queue[Job]":
        with self._lock:
            q = self._queues.get(channel)
            if q is None:
                q = queue.Queue()
                self._queues[channel] = q
                threading.Thread(target=self._worker_loop, args=(channel, q), daemon=True).start()
            return q

    def _worker_loop(self, channel: str, q: "queue.Queue[Job]") -> None:
        while True:
            job = q.get()
            try:
                if job.kind == "chat":
                    self._run_chat(channel, job)
                elif job.kind == "compact":
                    self._run_compact(channel, job)
                else:
                    logger.error(f"Unknown job kind: {job.kind!r}")
            except Exception:
                logger.exception(f"Unhandled error in worker for channel {channel!r}, job kind {job.kind!r}")

    def submit_chat(self, channel: str, user_message: str, max_tokens: int | None = None) -> "queue.Queue[str | None]":
        sse_queue: "queue.Queue[str | None]" = queue.Queue()
        job = Job(kind="chat", user_message=user_message, max_tokens=max_tokens, sse_queue=sse_queue)
        self._get_queue(channel).put(job)
        return sse_queue

    def submit_background(
        self,
        channel: str,
        prompt: str,
    ) -> None:
        job = Job(kind="chat", user_message=prompt)
        self._get_queue(channel).put(job)

    def submit_compact(self, channel: str) -> Any:
        """Enqueue a compact job and block until it completes.

        Intended to be called via asyncio.to_thread from request handlers.
        """
        result_queue: "queue.Queue[tuple[Any, Exception | None]]" = queue.Queue(maxsize=1)
        job = Job(kind="compact", result_queue=result_queue)
        self._get_queue(channel).put(job)
        result, exc = result_queue.get()
        if exc is not None:
            raise exc
        return result


def stream_queue(q: "queue.Queue[str | None]") -> Generator[str, None, None]:
    """SSE generator that blocks on a job-specific queue until the None sentinel."""
    while True:
        item = q.get()
        if item is None:
            return
        yield item

