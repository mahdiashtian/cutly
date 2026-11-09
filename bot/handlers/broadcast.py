"""Admin: composing a broadcast. Sending it is the worker's job.

The draft lives in the conversation data as plain ids (mode, audience, the
admin's message id) — not as a Telethon object in process memory — so it
survives restarts and can be read by the worker.
"""
from __future__ import annotations

from datetime import datetime

from bot import keyboards, texts
from bot.handlers.menus import admin_menu
from bot.keyboards import Btn
from bot.router import Access, Context, Router
from bot.states import State
from core.clock import parse_local, utcnow
from core.enums import BroadcastAudience, BroadcastMode
from schemas.channel import chat_peer

router = Router()
_AUDIENCES = {
    Btn.AUDIENCE_ALL: BroadcastAudience.ALL,
    Btn.AUDIENCE_NEW: BroadcastAudience.NEW,
    Btn.AUDIENCE_ACTIVE: BroadcastAudience.ACTIVE,
    Btn.AUDIENCE_INACTIVE: BroadcastAudience.INACTIVE,
    Btn.AUDIENCE_CHANNEL: BroadcastAudience.CHANNEL,
}


@router.text(Btn.FORWARD_ALL, access=Access.ADMIN, states={State.ADMIN_PANEL})
async def ask_forward(ctx: Context) -> None:
    await ctx.go(State.BROADCAST_CONTENT, mode=BroadcastMode.FORWARD)
    await ctx.reply(texts.ASK_BROADCAST_FORWARD, buttons=keyboards.BACK)


@router.text(Btn.COPY_ALL, access=Access.ADMIN, states={State.ADMIN_PANEL})
async def ask_copy(ctx: Context) -> None:
    await ctx.go(State.BROADCAST_CONTENT, mode=BroadcastMode.COPY)
    await ctx.reply(texts.ASK_BROADCAST_COPY, buttons=keyboards.BACK)


@router.state(State.BROADCAST_CONTENT, access=Access.ADMIN)
async def content(ctx: Context) -> None:
    if ctx.message.grouped_id:
        await ctx.reply(texts.BROADCAST_NO_ALBUM, buttons=keyboards.BACK)
        return
    await ctx.go(State.BROADCAST_AUDIENCE, **{**ctx.data, "message_id": ctx.message.id})
    await ctx.reply(texts.ASK_AUDIENCE, buttons=keyboards.BROADCAST_AUDIENCE)


@router.state(State.BROADCAST_AUDIENCE, access=Access.ADMIN)
async def audience(ctx: Context) -> None:
    chosen = _AUDIENCES.get(ctx.text)
    if chosen is None:
        await ctx.reply(texts.INVALID_AUDIENCE, buttons=keyboards.BROADCAST_AUDIENCE)
    elif chosen is BroadcastAudience.CHANNEL:
        await ctx.go(State.BROADCAST_CHANNEL, **{**ctx.data, "audience": chosen})
        await ctx.reply(texts.ASK_BROADCAST_CHANNEL, buttons=keyboards.BACK)
    else:
        await _preview(ctx, chosen, channel_ref=None)


@router.state(State.BROADCAST_CHANNEL, access=Access.ADMIN)
async def channel(ctx: Context) -> None:
    try:
        await ctx.app.client.get_entity(chat_peer(ctx.text))
    except Exception:  # noqa: BLE001 - any failure means we cannot check members
        await ctx.reply(texts.BROADCAST_CHANNEL_INVALID, buttons=keyboards.BACK)
        return
    await _preview(ctx, BroadcastAudience.CHANNEL, channel_ref=ctx.text)


async def _preview(ctx: Context, chosen: BroadcastAudience, *, channel_ref: str | None) -> None:
    count = await ctx.app.container.broadcasts.audience_size(chosen)
    if not count:
        await ctx.go(State.BROADCAST_AUDIENCE, **ctx.data)
        await ctx.reply(texts.BROADCAST_EMPTY, buttons=keyboards.BROADCAST_AUDIENCE)
        return
    data = {**ctx.data, "audience": chosen, "channel_ref": channel_ref}
    await ctx.go(State.BROADCAST_CONFIRM, **data)
    await ctx.reply(
        texts.BROADCAST_PREVIEW.format(
            mode=texts.MODE_LABELS[BroadcastMode(data["mode"])],
            audience=texts.AUDIENCE_LABELS[chosen], count=count,
            note=texts.BROADCAST_CHANNEL_NOTE if chosen is BroadcastAudience.CHANNEL else "",
        ),
        buttons=keyboards.BROADCAST_CONFIRM,
    )


@router.text(Btn.SEND_NOW, access=Access.ADMIN, states={State.BROADCAST_CONFIRM})
async def send_now(ctx: Context) -> None:
    broadcasts = ctx.app.container.broadcasts
    busy = await broadcasts.has_running()
    created = await _create(ctx, scheduled_at=None)
    await ctx.app.tasks.run_broadcast(created)
    await ctx.reply(texts.BROADCAST_QUEUED_BUSY if busy else texts.BROADCAST_QUEUED)
    await admin_menu(ctx)


@router.text(Btn.SCHEDULE, access=Access.ADMIN, states={State.BROADCAST_CONFIRM})
async def ask_schedule(ctx: Context) -> None:
    await ctx.go(State.BROADCAST_SCHEDULE, **ctx.data)
    await ctx.reply(texts.ASK_SCHEDULE, buttons=keyboards.BACK)


@router.state(State.BROADCAST_SCHEDULE, access=Access.ADMIN)
async def schedule(ctx: Context) -> None:
    zone = ctx.app.settings.timezone
    try:
        when = parse_local(ctx.text, zone)
    except ValueError:
        when = None
    if when is None or when <= utcnow():
        await ctx.reply(texts.INVALID_SCHEDULE, buttons=keyboards.BACK)
        return
    await _create(ctx, scheduled_at=when)
    await ctx.go(State.ADMIN_PANEL)
    await ctx.reply(texts.BROADCAST_SCHEDULED.format(when=ctx.app.local_time(when)), buttons=keyboards.ADMIN)


@router.text(Btn.CANCEL_BROADCAST, access=Access.ADMIN)
async def cancel(ctx: Context) -> None:
    """Drops the draft, cancels pending jobs and asks a running one to stop."""
    affected = await ctx.app.container.broadcasts.cancel_active()
    await ctx.go(State.ADMIN_PANEL)
    await ctx.reply(texts.BROADCAST_CANCEL_REQUESTED if affected else texts.BROADCAST_CANCELLED,
                    buttons=keyboards.ADMIN)


async def _create(ctx: Context, *, scheduled_at: datetime | None) -> int:
    broadcast = await ctx.app.container.broadcasts.create(
        admin_id=ctx.user_id,
        mode=BroadcastMode(ctx.data["mode"]),
        audience=BroadcastAudience(ctx.data["audience"]),
        channel_ref=ctx.data.get("channel_ref"),
        source_chat_id=ctx.user_id,
        source_message_id=ctx.data["message_id"],
        scheduled_at=scheduled_at,
    )
    return broadcast.id
