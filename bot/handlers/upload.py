"""Collecting files into an upload session and turning it into one share link."""
from __future__ import annotations

import logging
from datetime import timedelta

from telethon.tl.custom import Message

from bot import keyboards, texts
from bot.keyboards import Btn
from bot.media import MediaRef, extract_media
from bot.router import Context, Router
from bot.states import State
from core.clock import utcnow
from schemas.link import count_types

log = logging.getLogger(__name__)
router = Router()


@router.text(Btn.UPLOAD)
async def start_upload(ctx: Context) -> None:
    await ctx.app.container.uploads.start(ctx.user_id)
    await ctx.go(State.UPLOADING)
    await ctx.reply(texts.UPLOAD_START, buttons=keyboards.UPLOAD_SESSION)


@router.state(State.UPLOADING)
async def upload_file(ctx: Context) -> None:
    await _store(ctx, [ctx.message])


@router.album(State.UPLOADING)
async def upload_album(ctx: Context, messages: list[Message]) -> None:
    await _store(ctx, messages)


async def _store(ctx: Context, messages: list[Message]) -> None:
    """Forward to the storage channel (a durable copy) and add to the session."""
    app = ctx.app
    refs: list[MediaRef | None] = [extract_media(message) for message in messages]
    if None in refs:
        await ctx.reply(texts.UPLOAD_ALBUM_UNSUPPORTED if len(messages) > 1 else texts.UPLOAD_UNSUPPORTED)
        return
    storage = app.settings.storage_channel_id
    if not storage:
        await ctx.reply(texts.UPLOAD_NO_STORAGE)
        return
    uploads, limit = app.container.uploads, app.settings.upload_max_files
    if len(await uploads.items(ctx.user_id)) + len(refs) > limit:
        await ctx.reply(texts.UPLOAD_TOO_MANY.format(limit=limit), buttons=keyboards.UPLOAD_SESSION)
        return
    try:
        forwarded = await app.client.forward_messages(storage, messages)
    except Exception:
        log.exception("forwarding to the storage channel failed")
        await ctx.reply(texts.UPLOAD_STORE_FAILED)
        return
    added = await uploads.add(
        ctx.user_id, [ref.stored_as(copy.id) for ref, copy in zip(refs, forwarded, strict=True)], limit=limit
    )
    if added is None:  # a concurrent upload filled the session first
        await ctx.reply(texts.UPLOAD_TOO_MANY.format(limit=limit), buttons=keyboards.UPLOAD_SESSION)
        return
    items = await uploads.items(ctx.user_id)
    await ctx.reply(
        texts.UPLOAD_SAVED.format(count=len(items), size=texts.file_size(sum(i.size for i in items))),
        buttons=keyboards.UPLOAD_SESSION,
    )


@router.text(Btn.FINISH_UPLOAD, states={State.UPLOADING})
async def finish_upload(ctx: Context) -> None:
    if not await ctx.app.container.uploads.items(ctx.user_id):
        await ctx.reply(texts.UPLOAD_EMPTY, buttons=keyboards.MAIN)
        await ctx.go(State.IDLE)
        return
    await ctx.go(State.UPLOAD_LIMITS)
    await ctx.reply(texts.UPLOAD_ASK_LIMITS, buttons=keyboards.UPLOAD_LIMITS)


@router.text(Btn.CANCEL_UPLOAD, states={State.UPLOADING})
async def cancel_upload(ctx: Context) -> None:
    """Nothing reaches the database before «finish»; the storage copies stay."""
    uploads = ctx.app.container.uploads
    count = len(await uploads.items(ctx.user_id))
    await uploads.clear(ctx.user_id)
    await ctx.go(State.IDLE)
    await ctx.reply(texts.UPLOAD_CANCELLED.format(count=count) if count else texts.UPLOAD_EMPTY,
                    buttons=keyboards.MAIN)


@router.text(Btn.NO_LIMIT, states={State.UPLOAD_LIMITS})
async def no_limit(ctx: Context) -> None:
    await _create_link(ctx, days=None, downloads=None)


@router.state(State.UPLOAD_LIMITS)
async def upload_limits(ctx: Context) -> None:
    """``<days> <downloads>``; ``-`` drops either limit (but not both)."""
    parts = ctx.text.split()
    if len(parts) != 2:
        await ctx.reply(texts.UPLOAD_LIMITS_FORMAT, buttons=keyboards.UPLOAD_LIMITS)
        return
    try:
        days, downloads = _parse_limit(parts[0]), _parse_limit(parts[1])
        if days is None and downloads is None:
            raise ValueError("at least one limit is required")
    except ValueError:
        await ctx.reply(texts.UPLOAD_LIMITS_POSITIVE, buttons=keyboards.UPLOAD_LIMITS)
        return
    await _create_link(ctx, days=days, downloads=downloads)


def _parse_limit(part: str) -> int | None:
    if part == "-":
        return None
    value = int(part)
    if value < 1:
        raise ValueError("limits must be positive")
    return value


async def _create_link(ctx: Context, *, days: int | None, downloads: int | None) -> None:
    app, uploads = ctx.app, ctx.app.container.uploads
    items = await uploads.items(ctx.user_id)
    if not items:
        await ctx.reply(texts.UPLOAD_EMPTY, buttons=keyboards.MAIN)
        await ctx.go(State.IDLE)
        return
    try:
        link = await app.container.links.create(
            ctx.user_id, items,
            expires_at=utcnow() + timedelta(days=days) if days else None,
            max_downloads=downloads,
        )
    except Exception:
        log.exception("saving upload of user %s failed", ctx.user_id)
        await ctx.reply(texts.UPLOAD_SAVE_FAILED, buttons=keyboards.MAIN)
        return
    finally:
        await uploads.clear(ctx.user_id)
        await ctx.go(State.IDLE)
    await ctx.reply(
        texts.UPLOAD_DONE.format(
            summary=texts.media_summary(count_types(items)),
            size=texts.file_size(sum(item.size for item in items)),
            url=app.share_url(link.code),
        ),
        buttons=keyboards.MAIN,
    )
