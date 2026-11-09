"""Backup and restore jobs (they read or rewrite the whole database)."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient

from bot import keyboards, texts
from bot.states import State
from bot.telegram import user_peer
from container import Container
from repositories.redis.restores import StagedRestore
from services.restore import RestoreError

log = logging.getLogger(__name__)
# Lets requests that started just before maintenance mode finish first.
DRAIN_SECONDS = 2


async def _admin_peer(container: Container, admin_id: int):
    admin = await container.users.get(admin_id)
    return user_peer(admin_id, admin.access_hash if admin else None)


async def data_backup(container: Container, client: TelegramClient, admin_id: int) -> None:
    peer = await _admin_peer(container, admin_id)
    try:
        path = await container.backups.export_data()
    except Exception:
        log.exception("data backup failed")
        await client.send_message(peer, texts.DATA_BACKUP_FAILED, buttons=keyboards.ADMIN)
        return
    try:
        await client.send_file(peer, path, caption=texts.DATA_BACKUP_CAPTION, buttons=keyboards.ADMIN)
    finally:
        path.unlink(missing_ok=True)


async def full_backup(container: Container, client: TelegramClient, admin_id: int) -> None:
    peer = await _admin_peer(container, admin_id)
    path = await container.backups.full_dump()
    if path is None:
        await client.send_message(peer, texts.FULL_BACKUP_FAILED, buttons=keyboards.ADMIN)
        return
    try:
        await client.send_file(peer, path, caption=texts.FULL_BACKUP_CAPTION, buttons=keyboards.ADMIN)
    finally:
        path.unlink(missing_ok=True)


async def _move_admin(container: Container, admin_id: int, *, expected: State, to: State) -> bool:
    """Change the admin's state only if they are still waiting for this job."""
    conversation = await container.conversations.get(admin_id)
    if conversation.state != expected.name:
        return False
    await container.conversations.set(admin_id, to.name)
    return True


async def stage_restore(container: Container, client: TelegramClient, admin_id: int, upload: str) -> None:
    peer = await _admin_peer(container, admin_id)
    try:
        # Synchronous on purpose: it is CPU and disk bound, and this worker
        # process is not serving anything else meanwhile.
        staged = container.restores.stage(Path(upload))
    except Exception as error:
        if not isinstance(error, RestoreError):
            log.exception("staging a restore failed")
        reason = error if isinstance(error, RestoreError) else texts.UNEXPECTED_ERROR
        await _move_admin(container, admin_id, expected=State.RESTORE_WAITING, to=State.RESTORE_UPLOAD)
        await client.send_message(peer, texts.RESTORE_INVALID.format(reason=reason), buttons=keyboards.BACK)
        return
    finally:
        Path(upload).unlink(missing_ok=True)
    if not await _move_admin(container, admin_id, expected=State.RESTORE_WAITING, to=State.RESTORE_CONFIRM):
        Path(staged.staging_path).unlink(missing_ok=True)  # the admin moved on
        return
    await container.staged_restores.put(admin_id, staged)
    counts = "\n".join(f"{name}: {count:,}" for name, count in staged.counts.items())
    await client.send_message(
        peer, texts.RESTORE_PREVIEW.format(version=staged.revision, counts=counts),
        buttons=keyboards.RESTORE_CONFIRM,
    )


async def apply_restore(container: Container, client: TelegramClient, admin_id: int, staged: StagedRestore) -> None:
    peer = await _admin_peer(container, admin_id)
    if await container.broadcasts.has_running():
        Path(staged.staging_path).unlink(missing_ok=True)
        await client.send_message(peer, texts.RESTORE_BROADCAST_RUNNING, buttons=keyboards.ADMIN)
        return
    await container.maintenance.turn_on()
    safety: Path | None = None
    try:
        await asyncio.sleep(DRAIN_SECONDS)
        safety = await container.backups.export_data(prefix="before-restore")
        await container.restores.apply(staged)
        await container.reset_after_restore()
    except Exception:
        log.exception("restore failed")
        await client.send_message(peer, texts.RESTORE_FAILED, buttons=keyboards.ADMIN)
        return
    finally:
        await container.maintenance.turn_off()
        Path(staged.staging_path).unlink(missing_ok=True)
    await container.conversations.set(admin_id, State.ADMIN_PANEL.name)
    # The safety copy stays on the server even if sending it fails.
    await client.send_file(peer, safety, caption=texts.RESTORE_DONE, buttons=keyboards.ADMIN)
