"""Admin: backups and restore. The heavy lifting happens in the worker."""
from __future__ import annotations

import uuid
from pathlib import Path

from bot import keyboards, texts
from bot.keyboards import Btn
from bot.router import Access, Context, Router
from bot.states import State

router = Router()
PANEL = {State.ADMIN_PANEL}
RESTORE_STATES = frozenset({State.RESTORE_UPLOAD, State.RESTORE_WAITING, State.RESTORE_CONFIRM})


@router.text(Btn.FULL_BACKUP, access=Access.OWNER, states=PANEL)
async def full_backup(ctx: Context) -> None:
    await ctx.app.tasks.full_backup(ctx.user_id)
    await ctx.reply(texts.BACKUP_STARTED, buttons=keyboards.ADMIN)


@router.text(Btn.DATA_BACKUP, access=Access.OWNER, states=PANEL)
async def data_backup(ctx: Context) -> None:
    await ctx.app.tasks.data_backup(ctx.user_id)
    await ctx.reply(texts.BACKUP_STARTED, buttons=keyboards.ADMIN)


@router.text(Btn.RESTORE, access=Access.OWNER, states=PANEL)
async def ask_restore(ctx: Context) -> None:
    await discard_staged_restore(ctx)
    await ctx.go(State.RESTORE_UPLOAD)
    await ctx.reply(texts.ASK_RESTORE_FILE, buttons=keyboards.BACK)


@router.state(State.RESTORE_UPLOAD, access=Access.OWNER)
async def receive_backup(ctx: Context) -> None:
    document = ctx.message.document
    if document is None:
        await ctx.reply(texts.RESTORE_NEED_DOCUMENT, buttons=keyboards.BACK)
        return
    settings = ctx.app.settings
    if document.size > settings.restore_max_bytes:
        await ctx.reply(texts.RESTORE_TOO_LARGE, buttons=keyboards.BACK)
        return
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    path = (settings.backup_dir / f"upload-{uuid.uuid4().hex}.backup").resolve()
    await ctx.app.client.download_media(ctx.message, file=str(path))  # async, never blocks the loop
    await ctx.go(State.RESTORE_WAITING)
    await ctx.reply(texts.RESTORE_CHECKING, buttons=keyboards.BACK)
    await ctx.app.tasks.stage_restore(ctx.user_id, str(path))


@router.text(Btn.CONFIRM_RESTORE, access=Access.OWNER, states={State.RESTORE_CONFIRM})
async def confirm_restore(ctx: Context) -> None:
    container = ctx.app.container
    staged = await container.staged_restores.pop(ctx.user_id)
    await ctx.go(State.ADMIN_PANEL)
    if staged is None:
        await ctx.reply(texts.RESTORE_EXPIRED, buttons=keyboards.ADMIN)
        return
    if await container.broadcasts.has_running():
        Path(staged.staging_path).unlink(missing_ok=True)
        await ctx.reply(texts.RESTORE_BROADCAST_RUNNING, buttons=keyboards.ADMIN)
        return
    await ctx.app.tasks.apply_restore(ctx.user_id, staged.model_dump_json())
    await ctx.reply(texts.RESTORE_RUNNING, buttons=keyboards.ADMIN)


async def discard_staged_restore(ctx: Context) -> None:
    """Leaving the restore flow drops a validated-but-unconfirmed backup."""
    if ctx.state not in RESTORE_STATES:
        return
    staged = await ctx.app.container.staged_restores.pop(ctx.user_id)
    if staged is not None:
        Path(staged.staging_path).unlink(missing_ok=True)
