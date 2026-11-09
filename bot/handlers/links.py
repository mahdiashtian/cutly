"""Managing your own links: delete, caption, password, tracking, history.

Every action is "ask for a code, then act on it", so the flows share one
prompt helper and one lookup helper instead of nine copies of the same code.
"""
from __future__ import annotations

from bot import keyboards, texts
from bot.app import BotApp
from bot.handlers.menus import MAX_PASSWORD_LENGTH, valid_code
from bot.keyboards import Btn
from bot.router import CallbackContext, Context, Router
from bot.states import State
from schemas.link import LinkDTO, LinkSummary

router = Router()
HISTORY_PAGE_SIZE = 5


async def _ask(ctx: Context, state: State, prompt: str) -> None:
    await ctx.go(state)
    await ctx.reply(prompt, buttons=keyboards.BACK)


async def _owned_link(ctx: Context, code: str | None = None) -> LinkDTO | None:
    """The sender's link for the typed (or given) code; replies on failure."""
    code = valid_code(code if code is not None else ctx.text)
    if code is None:
        await ctx.reply(texts.INVALID_CODE, buttons=keyboards.BACK)
        return None
    link = await ctx.app.container.links.get_owned(code, ctx.user_id)
    if link is None:
        await ctx.reply(texts.LINK_NOT_FOUND_RETRY, buttons=keyboards.BACK)
    return link


async def _done(ctx: Context, message: str) -> None:
    await ctx.go(State.IDLE)
    await ctx.reply(message, buttons=keyboards.MAIN)


# ---- delete ----
@router.text(Btn.DELETE)
async def ask_delete(ctx: Context) -> None:
    await _ask(ctx, State.DELETE_CODE, texts.ASK_CODE_DELETE)


@router.state(State.DELETE_CODE)
async def delete(ctx: Context) -> None:
    code = valid_code(ctx.text)
    if code is None:
        await ctx.reply(texts.INVALID_CODE, buttons=keyboards.BACK)
    elif await ctx.app.container.links.delete_owned(code, ctx.user_id):
        await _done(ctx, texts.DELETED)
    else:
        await ctx.reply(texts.LINK_NOT_FOUND_RETRY, buttons=keyboards.BACK)


# ---- caption ----
@router.text(Btn.SET_CAPTION)
async def ask_caption_code(ctx: Context) -> None:
    await _ask(ctx, State.CAPTION_CODE, texts.ASK_CODE_CAPTION)


@router.state(State.CAPTION_CODE)
async def caption_code(ctx: Context) -> None:
    if link := await _owned_link(ctx):
        await ctx.go(State.CAPTION_TEXT, code=link.code)
        await ctx.reply(texts.ASK_CAPTION, buttons=keyboards.BACK)


@router.state(State.CAPTION_TEXT)
async def caption_text(ctx: Context) -> None:
    if link := await _owned_link(ctx, ctx.data.get("code", "")):
        await ctx.app.container.links.set_caption(link, ctx.text)
        await _done(ctx, texts.CAPTION_SET)


@router.text(Btn.UNSET_CAPTION)
async def ask_caption_remove(ctx: Context) -> None:
    await _ask(ctx, State.CAPTION_REMOVE_CODE, texts.ASK_CODE_CAPTION)


@router.state(State.CAPTION_REMOVE_CODE)
async def caption_remove(ctx: Context) -> None:
    if link := await _owned_link(ctx):
        await ctx.app.container.links.set_caption(link, None)
        await _done(ctx, texts.CAPTION_REMOVED)


# ---- password ----
@router.text(Btn.SET_PASSWORD)
async def ask_password_code(ctx: Context) -> None:
    await _ask(ctx, State.PASSWORD_CODE, texts.ASK_CODE_PASSWORD)


@router.state(State.PASSWORD_CODE)
async def password_code(ctx: Context) -> None:
    if link := await _owned_link(ctx):
        await ctx.go(State.PASSWORD_TEXT, code=link.code)
        await ctx.reply(texts.ASK_PASSWORD, buttons=keyboards.BACK)


@router.state(State.PASSWORD_TEXT)
async def password_text(ctx: Context) -> None:
    if not ctx.text:
        await ctx.reply(texts.ASK_PASSWORD, buttons=keyboards.BACK)
    elif len(ctx.text) > MAX_PASSWORD_LENGTH:
        await ctx.reply(texts.PASSWORD_TOO_LONG.format(limit=MAX_PASSWORD_LENGTH), buttons=keyboards.BACK)
    elif link := await _owned_link(ctx, ctx.data.get("code", "")):
        await ctx.app.container.links.set_password(link, ctx.text)
        await _done(ctx, texts.PASSWORD_SET)


@router.text(Btn.UNSET_PASSWORD)
async def ask_password_remove(ctx: Context) -> None:
    await _ask(ctx, State.PASSWORD_REMOVE_CODE, texts.ASK_CODE_PASSWORD)


@router.state(State.PASSWORD_REMOVE_CODE)
async def password_remove(ctx: Context) -> None:
    if link := await _owned_link(ctx):
        await ctx.app.container.links.set_password(link, None)
        await _done(ctx, texts.PASSWORD_REMOVED)


# ---- tracking ----
@router.text(Btn.TRACK)
async def ask_track(ctx: Context) -> None:
    await _ask(ctx, State.TRACK_CODE, texts.ASK_CODE_TRACK)


@router.state(State.TRACK_CODE)
async def track(ctx: Context) -> None:
    code = valid_code(ctx.text)
    if code is None:
        await ctx.reply(texts.INVALID_CODE, buttons=keyboards.BACK)
        return
    summary = await ctx.app.container.links.owned_summary(code, ctx.user_id)
    if summary is None:
        await ctx.reply(texts.LINK_NOT_FOUND_RETRY, buttons=keyboards.BACK)
        return
    app = ctx.app
    await _done(ctx, texts.TRACK.format(
        code=summary.code,
        kind=texts.media_kind(summary.type_counts),
        size=texts.file_size(summary.total_size),
        caption=summary.caption or texts.NONE,
        password=texts.HAS_PASSWORD if summary.has_password else texts.NONE,
        downloads=summary.download_count,
        expires=app.local_time(summary.expires_at) or texts.NO_EXPIRY,
        max_downloads=summary.max_downloads or texts.NO_LIMIT,
        created=app.local_time(summary.created_at),
        url=app.share_url(summary.code),
    ))


# ---- history (paginated with inline buttons, not one message per 5 links) ----
@router.text(Btn.HISTORY)
async def history(ctx: Context) -> None:
    text, buttons = await _history_page(ctx.app, ctx.user_id, 0)
    await ctx.reply(text, buttons=buttons or keyboards.MAIN)


@router.callback("hist")
async def history_page(ctx: CallbackContext) -> None:
    text, buttons = await _history_page(ctx.app, ctx.user_id, int(ctx.args[0]))
    await ctx.event.edit(text, buttons=buttons)
    await ctx.event.answer()


async def _history_page(app: BotApp, owner_id: int, page: int):
    items, total, page = await app.container.links.owned_page(owner_id, page, HISTORY_PAGE_SIZE)
    if not total:
        return texts.LINK_NOT_FOUND, None
    pages = (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE
    lines = [_history_item(app, page * HISTORY_PAGE_SIZE + index, item) for index, item in enumerate(items, 1)]
    title = texts.HISTORY_TITLE.format(page=page + 1, pages=pages, total=total)
    return title + "\n" + texts.HISTORY_SEPARATOR.join(lines), keyboards.pager("hist", page, pages)


def _history_item(app: BotApp, index: int, item: LinkSummary) -> str:
    return texts.HISTORY_ITEM.format(
        index=index, code=item.code, kind=texts.media_kind(item.type_counts),
        size=texts.file_size(item.total_size), created=app.local_time(item.created_at),
        downloads=item.download_count, expires=app.local_time(item.expires_at) or texts.NO_EXPIRY,
        max_downloads=item.max_downloads or texts.NO_LIMIT, url=app.share_url(item.code),
    )
