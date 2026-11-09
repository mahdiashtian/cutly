"""Opening a share link: password, limits, delivery, auto-delete."""
from __future__ import annotations

import logging

from bot import keyboards, texts
from bot.router import Context, Router
from bot.states import State
from schemas.link import LinkDTO

log = logging.getLogger(__name__)
router = Router()
# Telegram's caption limit, counted in UTF-16 code units (an emoji counts twice).
CAPTION_LIMIT = 1024


def fit_caption(body: str, footer: str) -> str:
    """Trim the admin/owner text, never the footer: an over-long caption would
    make Telegram reject the whole delivery."""
    def units(text: str) -> int:
        return len(text.encode("utf-16-le")) // 2

    room = CAPTION_LIMIT - units(footer)
    if units(body) <= room:
        return body + footer
    while body and units(body) > room - 1:
        body = body[:-1]
    return body + "…" + footer


async def open_link(ctx: Context, code: str) -> None:
    link = await ctx.app.container.links.get(code)
    if link is None:
        await ctx.reply(texts.LINK_NOT_FOUND, buttons=keyboards.MAIN)
        return
    if link.is_expired:
        await ctx.reply(texts.LINK_EXPIRED, buttons=keyboards.MAIN)
        return
    if link.password_hash and link.owner_id != ctx.user_id:
        await ctx.go(State.LINK_PASSWORD, code=code)
        await ctx.reply(texts.ASK_LINK_PASSWORD, buttons=keyboards.BACK)
        return
    await deliver(ctx, link)


@router.state(State.LINK_PASSWORD)
async def link_password(ctx: Context) -> None:
    links = ctx.app.container.links
    link = await links.get(ctx.data.get("code", ""))
    if link is None:
        await ctx.go(State.IDLE)
        await ctx.reply(texts.LINK_NOT_FOUND, buttons=keyboards.MAIN)
        return
    if not await links.check_password(link, ctx.text):
        await ctx.reply(texts.WRONG_PASSWORD, buttons=keyboards.BACK)
        return
    await ctx.go(State.IDLE)
    await deliver(ctx, link)


async def deliver(ctx: Context, link: LinkDTO) -> None:
    """Reserve a download slot, send, then either keep or give back the slot.

    Reserving first (one atomic UPDATE) is what makes the download cap exact
    under concurrency; giving the slot back on failure keeps failed sends from
    eating into it.
    """
    app, links = ctx.app, ctx.app.container.links
    count = await links.reserve_download(link)
    if count is None:
        await ctx.reply(texts.LINK_EXHAUSTED, buttons=keyboards.MAIN)
        return
    settings = await app.container.settings_service.get()
    seconds = app.settings.delete_after_seconds
    caption = fit_caption(
        settings.caption_for(link.caption),
        texts.DELIVERY_FOOTER.format(count=count, seconds=seconds, bot=app.username),
    )
    try:
        messages = await app.delivery.send(ctx.user_id, link, caption)
    except Exception:
        log.exception("delivery of %s failed", link.code)
        await links.release_download(link)
        await ctx.reply(texts.DELIVERY_FAILED, buttons=keyboards.MAIN)
        return
    await links.record_view(link, ctx.user_id)
    # Deleting later is the worker's job: it survives a bot restart, unlike a timer here.
    await app.tasks.delete_messages_later(ctx.user_id, [message.id for message in messages], seconds)
