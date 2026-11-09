"""Celery task definitions: thin synchronous wrappers around async jobs.

Delivery guarantees, chosen per task:
* ``acks_late=True`` only where running twice is harmless (deleting messages,
  polling, cleanup): a crashed worker's task is then redelivered.
* Everything user-visible (backups, restore, broadcasts) is acknowledged on
  receipt, so it can never run twice; broadcasts recover from crashes through
  their own heartbeat/cursor instead.
"""
from __future__ import annotations

from telethon.errors import FloodWaitError

from repositories.redis.restores import StagedRestore
from worker.app import celery_app
from worker.jobs import backups, broadcast, maintenance
from worker.queue import TaskName
from worker.runtime import WorkerRuntime, runtime


@celery_app.task(name=TaskName.DELETE_MESSAGES, bind=True, acks_late=True, max_retries=5)
def delete_messages(self, chat_id: int, message_ids: list[int]) -> None:
    async def job(rt: WorkerRuntime) -> None:
        await maintenance.delete_messages(await rt.telegram(), message_ids)

    try:
        runtime.run(job)
    except FloodWaitError as error:
        raise self.retry(countdown=error.seconds + 1) from error


@celery_app.task(name=TaskName.RUN_BROADCAST)
def run_broadcast(broadcast_id: int) -> None:
    async def job(rt: WorkerRuntime) -> None:
        container = await rt.container()
        if await broadcast.run_broadcast(container, await rt.telegram(), broadcast_id):
            await rt.queue.dispatch_broadcasts()  # start the next queued one right away

    runtime.run(job)


@celery_app.task(name=TaskName.DISPATCH_BROADCASTS, acks_late=True)
def dispatch_broadcasts() -> None:
    async def job(rt: WorkerRuntime) -> None:
        await maintenance.dispatch_broadcasts(await rt.container(), rt.queue.run_broadcast)

    runtime.run(job)


@celery_app.task(name=TaskName.DATA_BACKUP)
def data_backup(admin_id: int) -> None:
    async def job(rt: WorkerRuntime) -> None:
        await backups.data_backup(await rt.container(), await rt.telegram(), admin_id)

    runtime.run(job)


@celery_app.task(name=TaskName.FULL_BACKUP)
def full_backup(admin_id: int) -> None:
    async def job(rt: WorkerRuntime) -> None:
        await backups.full_backup(await rt.container(), await rt.telegram(), admin_id)

    runtime.run(job)


@celery_app.task(name=TaskName.STAGE_RESTORE)
def stage_restore(admin_id: int, upload_path: str) -> None:
    async def job(rt: WorkerRuntime) -> None:
        await backups.stage_restore(await rt.container(), await rt.telegram(), admin_id, upload_path)

    runtime.run(job)


@celery_app.task(name=TaskName.APPLY_RESTORE)
def apply_restore(admin_id: int, staged_json: str) -> None:
    async def job(rt: WorkerRuntime) -> None:
        staged = StagedRestore.model_validate_json(staged_json)
        await backups.apply_restore(await rt.container(), await rt.telegram(), admin_id, staged)

    runtime.run(job)


@celery_app.task(name=TaskName.CLEANUP_FILES, acks_late=True)
def cleanup_files() -> None:
    async def job(rt: WorkerRuntime) -> None:
        maintenance.cleanup_files((await rt.container()).settings.backup_dir)

    runtime.run(job)


@celery_app.task(name=TaskName.REFRESH_CHANNEL_TITLES, acks_late=True)
def refresh_channel_titles() -> None:
    async def job(rt: WorkerRuntime) -> None:
        await maintenance.refresh_channel_titles(await rt.container(), await rt.telegram())

    runtime.run(job)
