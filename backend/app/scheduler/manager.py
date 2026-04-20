from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.scheduler.models import ScheduledTask, TriggerType

logger = logging.getLogger(__name__)


class SchedulerManager:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._tasks: dict[str, ScheduledTask] = {}
        # Injected after JobManager is available
        self._enqueue_fn = None
        self._broadcast_fn = None

    def set_enqueue(self, fn) -> None:
        """Wire up JobManager.enqueue after both managers are initialised."""
        self._enqueue_fn = fn

    def set_broadcast(self, fn) -> None:
        """Wire up WebSocket broadcast for scheduler_trigger events."""
        self._broadcast_fn = fn

    async def start(self) -> None:
        self._scheduler.start()
        logger.info("SchedulerManager started")

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("SchedulerManager stopped")

    # ------------------------------------------------------------------
    # Task CRUD
    # ------------------------------------------------------------------

    def add_task(
        self,
        name: str,
        job_type: str,
        project_id: int,
        trigger_type: TriggerType,
        trigger_config: dict[str, Any],
        payload: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> ScheduledTask:
        task = ScheduledTask(
            name=name,
            job_type=job_type,
            project_id=project_id,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            payload=payload or {},
            enabled=enabled,
        )
        self._tasks[task.id] = task
        if enabled:
            self._register_apscheduler_job(task)
        return task

    def remove_task(self, task_id: str) -> bool:
        task = self._tasks.pop(task_id, None)
        if task is None:
            return False
        self._remove_apscheduler_job(task_id)
        return True

    def enable_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if not task.enabled:
            task.enabled = True
            self._register_apscheduler_job(task)
        return True

    def disable_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.enabled:
            task.enabled = False
            self._remove_apscheduler_job(task_id)
        return True

    def get_task(self, task_id: str) -> ScheduledTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[ScheduledTask]:
        return list(self._tasks.values())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apscheduler_job_id(self, task_id: str) -> str:
        return f"scheduled_task_{task_id}"

    def _build_trigger(self, task: ScheduledTask):
        if task.trigger_type == TriggerType.CRON:
            return CronTrigger(**task.trigger_config)
        return IntervalTrigger(**task.trigger_config)

    def _register_apscheduler_job(self, task: ScheduledTask) -> None:
        job_id = self._apscheduler_job_id(task.id)
        trigger = self._build_trigger(task)
        self._scheduler.add_job(
            self._fire_task,
            trigger=trigger,
            id=job_id,
            args=[task.id],
            replace_existing=True,
        )
        logger.info("Registered schedule '%s' (%s)", task.name, task.id)

    def _remove_apscheduler_job(self, task_id: str) -> None:
        job_id = self._apscheduler_job_id(task_id)
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            logger.info("Removed schedule job %s", task_id)

    async def _fire_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None or not task.enabled:
            return
        task.last_triggered_at = datetime.utcnow()
        logger.info("Schedule '%s' fired, enqueueing job type '%s'", task.name, task.job_type)
        if self._enqueue_fn:
            job = await self._enqueue_fn(
                task.job_type,
                task.project_id,
                task.payload,
            )
            if self._broadcast_fn:
                await self._broadcast_fn("scheduler_trigger", {"schedule_id": task_id, "job_id": job.id})


# Singleton
scheduler_manager = SchedulerManager()
