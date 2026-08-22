"""Single-thread job queue for image generation (24GB safe)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from src.engine import EngineError, engine


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    error = "error"


@dataclass
class Job:
    id: str
    status: JobStatus = JobStatus.queued
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    progress: float = 0.0
    message: str = "Queued"
    step: int | None = None
    steps: int | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    request: dict[str, Any] = field(default_factory=dict)


class JobQueue:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._cv = threading.Condition()
        self._thread = threading.Thread(target=self._loop, name="studio-jobs", daemon=True)
        self._thread.start()

    def submit(self, request: dict[str, Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], request=request)
        with self._cv:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._cv.notify()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_recent(self, limit: int = 50) -> list[Job]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._order:
                    self._cv.wait()
                job_id = self._order.pop(0)
                job = self._jobs[job_id]

            self._run(job)

    def _run(self, job: Job) -> None:
        job.status = JobStatus.running
        job.started_at = time.time()
        job.message = "Starting…"
        job.progress = 0.02
        job.steps = int(job.request.get("steps") or 4)
        req = job.request

        def on_progress(info: dict[str, Any]) -> None:
            if info.get("progress") is not None:
                job.progress = float(info["progress"])
            if info.get("message"):
                job.message = str(info["message"])
            if info.get("step") is not None:
                job.step = int(info["step"])
            if info.get("steps") is not None:
                job.steps = int(info["steps"])

        stop = threading.Event()

        def poll_backend_progress() -> None:
            while not stop.wait(0.35):
                try:
                    info = engine.poll_progress()
                except Exception:
                    continue
                if info:
                    on_progress(info)

        poller = threading.Thread(target=poll_backend_progress, name="studio-progress", daemon=True)
        poller.start()
        try:
            path = engine.generate(
                prompt=req["prompt"],
                width=int(req.get("width") or 1024),
                height=int(req.get("height") or 576),
                steps=int(req.get("steps") or 4),
                seed=req.get("seed"),
                quantize=int(req.get("quantize") or 4),
                loras=req.get("loras") or [],
                ref_images=req.get("ref_images") or [],
                on_progress=on_progress,
                mode=str(req.get("mode") or "gen"),
                image_strength=req.get("image_strength"),
                guidance=req.get("guidance"),
                system_mode=req.get("system_mode"),
            )
            job.progress = 1.0
            job.status = JobStatus.done
            job.message = "Done"
            job.result = {
                "image_path": str(path),
                "image_url": f"/outputs/{Path(path).name}",
                "seed": req.get("seed"),
                "prompt": req["prompt"],
                "loras": req.get("loras") or [],
            }
        except EngineError as e:
            job.status = JobStatus.error
            job.error = str(e)
            job.message = "Engine error"
        except Exception as e:  # noqa: BLE001
            job.status = JobStatus.error
            job.error = f"{type(e).__name__}: {e}"
            job.message = "Failed"
        finally:
            stop.set()
            poller.join(timeout=1.0)
            job.finished_at = time.time()


jobs = JobQueue()
