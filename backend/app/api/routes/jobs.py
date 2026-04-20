from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.core.database import AsyncSessionLocal
from app.db.models import JobRecord, Project
from app.jobs.manager import job_manager

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobOut(BaseModel):
    id: int
    project_id: int
    file_id: int | None
    job_type: str
    status: str
    dedupe_key: str
    priority: int
    payload_json: str | None
    attempt_count: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    scheduled_at: str
    started_at: str | None
    finished_at: str | None
    created_at: str
    updated_at: str
    progress: float | None = None
    message: str | None = None
    project_name: str = ""

    model_config = {"from_attributes": True}


def _with_progress(job: JobRecord, project_name: str = "") -> JobOut:
    out = JobOut.model_validate(job)
    out.project_name = project_name
    prog = job_manager._progress.get(job.id)
    if prog:
        out.progress = prog.progress
        out.message = prog.message
    return out


@router.get("/active", response_model=list[JobOut])
async def list_active_jobs() -> list[JobOut]:
    async with AsyncSessionLocal() as session:
        rows = await session.scalars(
            select(JobRecord)
            .where(JobRecord.status.in_(["queued", "running"]))
            .order_by(JobRecord.created_at)
        )
        jobs = rows.all()
        project_ids = {j.project_id for j in jobs}
        project_names: dict[int, str] = {}
        if project_ids:
            proj_rows = await session.scalars(
                select(Project).where(Project.id.in_(project_ids))
            )
            project_names = {p.id: p.name for p in proj_rows.all()}
        return [_with_progress(j, project_names.get(j.project_id, "")) for j in jobs]


@router.post("/{job_id}/cancel", status_code=200, response_model=dict)
async def cancel_job(job_id: int):
    async with AsyncSessionLocal() as session:
        job = await session.get(JobRecord, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status not in ("queued", "running"):
            raise HTTPException(status_code=409, detail="Job is not cancellable")
        project_id = job.project_id

    cancelled = await job_manager.cancel_job(job_id)
    if not cancelled:
        # Running job — mark cancelled directly; worker thread will finish naturally
        # but we trigger orchestration now so queued jobs start without waiting.
        from datetime import datetime
        from sqlalchemy import update as sa_update
        from app.db.models import JobStatus
        async with AsyncSessionLocal() as session:
            await session.execute(
                sa_update(JobRecord)
                .where(JobRecord.id == job_id)
                .values(
                    status=JobStatus.CANCELLED.value,
                    finished_at=datetime.utcnow().isoformat(),
                    updated_at=datetime.utcnow().isoformat(),
                )
            )
            await session.commit()
        job_manager._progress.pop(job_id, None)
        await job_manager._emit("job_update", job_id)

        # Trigger orchestration immediately so queued jobs don't wait for the
        # worker thread to finish the (now-cancelled) external call.
        if job_manager._on_complete:
            try:
                await job_manager._on_complete(job_id)
            except Exception:
                pass

    return {"cancelled": True}
@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: int) -> JobOut:
    async with AsyncSessionLocal() as session:
        job = await session.get(JobRecord, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        project = await session.get(Project, job.project_id)
        project_name = project.name if project else ""
    return _with_progress(job, project_name)


@router.get("/stats/durations", response_model=dict[str, dict])
async def get_job_duration_stats() -> dict[str, dict]:
    """Return avg duration (seconds) per job_type from last 100 completed runs each."""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT job_type,
                   AVG((julianday(finished_at) - julianday(started_at)) * 86400) AS avg_secs,
                   COUNT(*) AS sample_count
            FROM (
                SELECT job_type, started_at, finished_at,
                       ROW_NUMBER() OVER (PARTITION BY job_type ORDER BY finished_at DESC) AS rn
                FROM jobs
                WHERE status = 'completed'
                  AND started_at IS NOT NULL
                  AND finished_at IS NOT NULL
            ) sub
            WHERE rn <= 100
            GROUP BY job_type
        """))).fetchall()
    return {
        row.job_type: {"avg_secs": round(float(row.avg_secs), 2), "sample_count": int(row.sample_count)}
        for row in rows
    }