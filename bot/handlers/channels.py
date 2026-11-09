"""Admin: mandatory-join channels."""
from __future__ import annotations

import re

from bot import keyboards, texts
from bot.handlers.menus import join_menu
from bot.keyboards import Btn
from bot.router import Context, Router
from bot.states import State
from schemas.channel import chat_peer

router = Router()
_PUBLIC_REF = re.compile(r"@(\S+)")


@router.text(Btn.JOIN_PANEL, admin=True, states={State.ADMIN_PANEL})
async def open_panel(ctx: Context) -> None:
    await join_menu(ctx)


@router.text(Btn.LIST_CHANNELS, admin=True, states={State.JOIN_PANEL})
async def list_channels(ctx: Context) -> None:
    channels = await ctx.app.container.channels.list()
    text = texts.CHANNEL_LIST_TITLE + "".join(
        texts.CHANNEL_LIST_ITEM.format(link=channel.invite_link, ref=channel.chat_ref) for channel in channels
    ) if channels else texts.NO_CHANNELS
    await ctx.reply(text, buttons=keyboards.JOIN_PANEL)


@router.text(Btn.ADD_CHANNEL, admin=True, states={State.JOIN_PANEL})
async def ask_add(ctx: Context) -> None:
    await ctx.go(State.CHANNEL_ADD)
    await ctx.reply(texts.ASK_CHANNEL_ADD, buttons=keyboards.BACK)


@router.state(State.CHANNEL_ADD, admin=True)
async def add(ctx: Context) -> None:
    parsed = parse_channel(ctx.text)
    if parsed is None:
        await ctx.reply(texts.CHANNEL_FORMAT, buttons=keyboards.BACK)
        return
    chat_ref, invite_link = parsed
    # Resolving now both validates access (a channel the bot cannot see would
    # lock every user out) and gives the title shown on the join button.
    try:
        entity = await ctx.app.client.get_entity(chat_peer(chat_ref))
    except Exception:  # noqa: BLE001
        await ctx.reply(texts.CHANNEL_UNREACHABLE, buttons=keyboards.BACK)
        return
    title = getattr(entity, "title", None) or chat_ref
    if not await ctx.app.container.channels.add(chat_ref=chat_ref, invite_link=invite_link, title=title):
        await ctx.reply(texts.CHANNEL_EXISTS, buttons=keyboards.BACK)
        return
    await ctx.go(State.JOIN_PANEL)
    await ctx.reply(texts.CHANNEL_ADDED, buttons=keyboards.JOIN_PANEL)


@router.text(Btn.REMOVE_CHANNEL, admin=True, states={State.JOIN_PANEL})
async def ask_remove(ctx: Context) -> None:
    await ctx.go(State.CHANNEL_REMOVE)
    await ctx.reply(texts.ASK_CHANNEL_REMOVE, buttons=keyboards.BACK)


@router.state(State.CHANNEL_REMOVE, admin=True)
async def remove(ctx: Context) -> None:
    if await ctx.app.container.channels.remove(ctx.text):
        await ctx.go(State.JOIN_PANEL)
        await ctx.reply(texts.CHANNEL_REMOVED, buttons=keyboards.JOIN_PANEL)
    else:
        await ctx.reply(texts.CHANNEL_NOT_FOUND, buttons=keyboards.BACK)


def parse_channel(text: str) -> tuple[str, str] | None:
    """``@public`` -> ``("public", "https://t.me/public")``;
    ``"<invite link>\\n<-100 id>"`` -> ``("-100…", "<invite link>")``."""
    if match := _PUBLIC_REF.search(text):
        name = match.group(1)
        return name, f"https://t.me/{name}"
    parts = text.split()
    if len(parts) != 2:
        return None
    invite_link, chat_ref = parts
    return chat_ref, invite_link
