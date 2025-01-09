from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import httpx
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobEvent, JobExecutionEvent
from apscheduler.schedulers.base import SchedulerAlreadyRunningError
from apscheduler.triggers.date import DateTrigger
from fastapi.encoders import jsonable_encoder
from loguru import logger
from sqlmodel import col, select

from langflow.scheduling.jobstore import AsyncSQLModelJobStore
from langflow.scheduling.scheduler import AsyncScheduler
from langflow.services.base import Service
from langflow.services.database.models.job.model import Job, JobRead, JobStatus
from langflow.services.deps import session_scope
from langflow.services.jobs.schema import WebhookJobData

if TYPE_CHECKING:
    from collections.abc import Callable

    from apscheduler.job import Job as APSJob

    from langflow.services.database.service import DatabaseService
    from langflow.services.settings.service import SettingsService


class JobsService(Service):
    """Service for managing asynchronous tasks and scheduled flows.

    This service provides functionality to schedule, execute, monitor and manage background tasks
    using APScheduler. It supports one-time tasks scheduled for future execution.

    Attributes:
        name (str): The name identifier for this service
        settings_service (SettingsService): Service for accessing application settings
        database_service (DatabaseService): Service for database operations
        scheduler (AsyncScheduler | None): The async task scheduler instance
        job_store (AsyncSQLModelJobStore | None): Store for persisting job information
        _started (bool): Flag indicating if scheduler is running
    """

    name = "jobs_service"

    def __init__(self, settings_service: SettingsService, database_service: DatabaseService):
        """Initialize the task service.

        Args:
            settings_service: Service for accessing application settings
            database_service: Service for database operations
        """
        self.settings_service = settings_service
        self._started = False
        self.scheduler: AsyncScheduler | None = None
        self.job_store: AsyncSQLModelJobStore | None = None
        self.database_service = database_service

    async def setup(self):
        """Initialize and configure the task scheduler and job store.

        Sets up the AsyncScheduler with a SQLModel-based job store and configures
        event listeners for job execution and error handling.
        """
        self.scheduler = AsyncScheduler()
        await self.scheduler.configure()
        self.job_store = AsyncSQLModelJobStore()
        await self.scheduler.add_jobstore(self.job_store, "default")

        # Add event listeners
        await self.scheduler.add_listener(self._handle_job_executed, EVENT_JOB_EXECUTED)
        await self.scheduler.add_listener(self._handle_job_error, EVENT_JOB_ERROR)

    async def _ensure_scheduler_running(self):
        """Ensure the scheduler is initialized and running.

        Initializes the scheduler if needed and starts it if not already running.
        Handles the case where scheduler is already running gracefully.
        """
        if not self._started:
            if self.scheduler is None:
                await self.setup()
            try:
                await self.scheduler.start(paused=False)
                self._started = True
            except SchedulerAlreadyRunningError:
                pass

    async def _handle_job_executed(self, event: JobExecutionEvent) -> None:
        """Handle successful job execution events.

        Updates the job status to COMPLETED and stores the execution result.
        Sends webhook notification if enabled.

        Args:
            event: The job execution event containing job ID and result
        """
        await self._ensure_scheduler_running()
        async with session_scope() as session:
            job = await self._get_job_by_id(event.job_id, session)
            if job:
                await self._update_completed_job(job, event, session)
                await session.commit()
                await session.refresh(job)
                if self.settings_service.settings.job_webhook_enabled:
                    await self._send_job_webhook(job)

    async def _get_job_by_id(self, job_id: str, session) -> Job | None:
        """Get a job by its ID."""
        stmt = select(Job).where(Job.id == job_id)
        return (await session.exec(stmt)).first()

    async def _update_completed_job(self, job: Job, event: JobExecutionEvent, session) -> None:
        """Update job with completion details and result."""
        job.status = JobStatus.COMPLETED
        job.result = await self._serialize_job_result(event.retval)
        session.add(job)

    async def _serialize_job_result(self, result: Any) -> dict:
        """Serialize job result to JSON-compatible format."""
        try:
            serialized_result = jsonable_encoder(
                result, custom_encoder={datetime: lambda v: v.isoformat(), UUID: lambda v: str(v)}
            )
            if isinstance(serialized_result, dict):
                return serialized_result
            return {"output": str(result)}
        except (TypeError, ValueError) as e:
            logger.error("Error serializing result: %s", str(e))
            return {"output": str(result)}

    async def _send_job_webhook(self, job: Job) -> None:
        """Prepare and send webhook notification for completed job."""
        job_data = WebhookJobData(
            id=str(job.id),
            status=job.status.value if isinstance(job.status, Enum) else job.status,
            result=job.result,
            name=job.name,
            flow_id=str(job.flow_id) if job.flow_id else None,
            user_id=str(job.user_id) if job.user_id else None,
        )
        await self.send_webhook_notification(job_data)

    async def _handle_job_error(self, event: JobEvent) -> None:
        """Handle job execution error events.

        Updates the job status to FAILED and stores the error information.

        Args:
            event: The job event containing job ID and exception details
        """
        await self._ensure_scheduler_running()
        async with session_scope() as session:
            job = await self._get_job_by_id(event.job_id, session)
            if job:
                job.status = JobStatus.FAILED
                job.error = str(event.exception)
                session.add(job)
                await session.commit()

    async def create_job(
        self,
        task_func: str | Callable[..., Any],
        run_at: datetime | None = None,
        name: str | None = None,
        args: list | None = None,
        kwargs: dict | None = None,
    ) -> str:
        """Create and schedule a new job.

        Args:
            task_func: The function to execute or its string reference
            run_at: Optional datetime when the task should run
            name: Optional name for the task
            args: Optional positional arguments for the task
            kwargs: Optional keyword arguments for the task

        Returns:
            str: The unique identifier for the created job

        Raises:
            ValueError: If scheduler or job store is not initialized
            Exception: If job creation fails
        """
        await self._ensure_scheduler_running()
        if self.scheduler is None or self.job_store is None:
            msg = "Scheduler or job store not initialized"
            logger.error(msg)
            raise ValueError(msg)
        task_id = str(uuid4())
        try:
            trigger = DateTrigger(run_date=run_at) if run_at is not None else None

            await self.scheduler.add_job(
                task_func,
                trigger=trigger,
                args=args or [],
                kwargs=kwargs or {},
                id=task_id,
                name=name or f"task_{task_id}",
                misfire_grace_time=None,  # Run immediately when missed
                coalesce=True,  # Only run once if multiple are due
                max_instances=1,  # Only one instance at a time
                replace_existing=True,
            )

        except Exception as exc:
            logger.error(f"Error creating task: {exc}")
            raise
        return task_id

    async def get_job(self, job_id: str, user_id: UUID | None = None) -> APSJob | None:
        """Retrieve information about a specific job.

        Args:
            job_id: The unique identifier of the job
            user_id: Optional user ID to verify job ownership

        Returns:
            APSJob | None: The job if found, None otherwise

        Raises:
            ValueError: If job store is not initialized
            Exception: If job lookup fails
        """
        await self._ensure_scheduler_running()
        if self.job_store is None:
            msg = "Job store not initialized"
            logger.error(msg)
            raise ValueError(msg)
        try:
            job = await self.job_store.lookup_job(job_id, user_id)
        except Exception as exc:
            logger.error(f"Error getting job {job_id}: {exc}")
            raise
        return job

    async def cancel_job(self, job_id: str, user_id: UUID | None = None) -> bool:
        """Cancel a scheduled job.

        Args:
            job_id: The unique identifier of the job to cancel
            user_id: Optional user ID to verify job ownership

        Returns:
            bool: True if job was cancelled, False if job not found

        Raises:
            ValueError: If scheduler or job store is not initialized
            Exception: If job cancellation fails
        """
        await self._ensure_scheduler_running()
        if self.scheduler is None or self.job_store is None:
            msg = "Scheduler or job store not initialized"
            logger.error(msg)
            raise ValueError(msg)
        try:
            # Get the job from jobstore
            job = await self.job_store.lookup_job(job_id, user_id)
            if not job:
                return False

            # Remove from scheduler if not yet executed
            scheduler_job = await self.scheduler.get_job(job_id)
            if scheduler_job is not None:
                await self.scheduler.remove_job(job_id)

            # Explicitly mark the job as cancelled in the job store
            async with session_scope() as session:
                stmt = select(Job).where(Job.id == job_id)
                task = (await session.exec(stmt)).first()
                if task:
                    task.status = JobStatus.CANCELLED
                    task.is_active = False
                    task.updated_at = datetime.now(timezone.utc)
                    session.add(task)
                    await session.commit()

        except Exception as exc:
            logger.error(f"Error cancelling job {job_id}: {exc}")
            raise
        return True

    async def get_jobs(
        self,
        user_id: UUID | None = None,
        pending: bool | None = None,
        status: JobStatus | None = None,
    ) -> list[JobRead]:
        """Get all jobs from the job store with optional filtering.

        Args:
            user_id: Optional user ID to filter jobs by owner
            pending: Optional boolean to filter by pending status
            status: Optional job status to filter by

        Returns:
            list[JobRead]: List of jobs matching the filter criteria

        Raises:
            ValueError: If job store is not initialized
            Exception: If retrieving jobs fails
        """
        await self._ensure_scheduler_running()
        if self.job_store is None:
            msg = "Job store not initialized"
            logger.error(msg)
            raise ValueError(msg)
        if user_id is None:
            msg = "User ID is required"
            logger.error(msg)
            raise ValueError(msg)
        try:
            if pending is not None:
                # When pending is provided, use job store's get_user_jobs which handles pending status
                jobs = await self.job_store.get_user_jobs(user_id, pending=pending, status=status)
                # Convert to list of IDs and fetch from database to ensure consistency
                ids = [job.id for job in jobs]
                async with session_scope() as session:
                    stmt = select(Job).where(col(Job.id).in_(ids))
                    db_jobs = (await session.exec(stmt)).all()
                    return [JobRead.model_validate(job, from_attributes=True) for job in db_jobs]
            else:
                # When pending is not provided, directly query the database
                async with session_scope() as session:
                    stmt = select(Job)
                    if user_id:
                        stmt = stmt.where(Job.user_id == user_id)
                    if status is not None:
                        stmt = stmt.where(Job.status == status)
                    db_jobs = (await session.exec(stmt)).all()
                    return [JobRead.model_validate(job, from_attributes=True) for job in db_jobs]
        except Exception as exc:
            logger.error(f"Error getting tasks: {exc}")
            raise

    async def get_user_jobs(self, user_id: UUID) -> list[JobRead]:
        """Get all jobs for a specific user.

        Args:
            user_id: The ID of the user whose jobs to retrieve

        Returns:
            list[dict]: List of jobs belonging to the user

        Raises:
            ValueError: If job store is not initialized
            Exception: If retrieving jobs fails
        """
        await self._ensure_scheduler_running()
        if self.job_store is None:
            msg = "Job store not initialized"
            logger.error(msg)
            raise ValueError(msg)
        try:
            jobs = await self.job_store.get_user_jobs(user_id)
            return [JobRead.model_validate(job, from_attributes=True) for job in jobs]
        except Exception as exc:
            logger.error(f"Error getting jobs for user {user_id}: {exc}")
            raise

    async def stop(self):
        """Stop the task scheduler.

        Shuts down the scheduler if it is currently running.
        """
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Task scheduler stopped")

    async def send_webhook_notification(self, job_data: WebhookJobData) -> bool:
        """Send webhook notification for job completion."""
        if not self.settings_service.settings.job_webhook_enabled or not self.settings_service.settings.job_webhook_url:
            return False

        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.settings_service.settings.user_agent,
        }

        # Add secret key to headers if configured
        if self.settings_service.settings.job_webhook_secret:
            headers["X-Webhook-Secret"] = self.settings_service.settings.job_webhook_secret

        for attempt in range(self.settings_service.settings.job_webhook_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.settings_service.settings.job_webhook_url,
                        json=job_data.model_dump(),
                        headers=headers,
                        timeout=self.settings_service.settings.job_webhook_timeout,
                    )
                    response.raise_for_status()
                    logger.debug(f"Webhook notification sent successfully for job {job_data.id}")
                    return True
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                logger.warning(f"Webhook delivery attempt {attempt + 1} failed: {exc!s}")
                if attempt == self.settings_service.settings.job_webhook_retries - 1:
                    logger.error(f"Failed to send webhook notification for job {job_data.id}")
                    return False
        return False
