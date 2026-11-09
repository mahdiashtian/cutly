"""Admin panel: admins, statistics and the per-user access log."""
from __future__ import annotations

import asyncio

from bot import keyboards, texts
from bot.app import BotApp
from bot.handlers.menus import admin_menu, parse_positive_int
from bot.keyboards import Btn
from bot.router import CallbackContext, Context, Router
from bot.states import State

router = Router()
PANEL = {State.ADMIN_PANEL}
LOG_PAGE_SIZE = 10
# Bounds concurrent get_entity calls when listing admins.
_ENTITY_CONCURRENCY = 5


@router.text("/admin", admin=True)
async def open_panel(ctx: Context) -> None:
    await admin_menu(ctx)


# ---- admins ----
@router.text(Btn.ADD_ADMIN, admin=True, states=PANEL)
async def ask_add_admin(ctx: Context) -> None:
    await ctx.go(State.ADMIN_ADD)
    await ctx.reply(texts.ASK_ADMIN_ID_ADD, buttons=keyboards.BACK)


@router.text(Btn.REMOVE_ADMIN, admin=True, states=PANEL)
async def ask_remove_admin(ctx: Context) -> None:
    await ctx.go(State.ADMIN_REMOVE)
    await ctx.reply(texts.ASK_ADMIN_ID_REMOVE, buttons=keyboards.BACK)


@router.state(State.ADMIN_ADD, admin=True)
async def add_admin(ctx: Context) -> None:
    await _set_admin(ctx, True, texts.ADMIN_ADDED)


@router.state(State.ADMIN_REMOVE, admin=True)
async def remove_admin(ctx: Context) -> None:
    await _set_admin(ctx, False, texts.ADMIN_REMOVED)


async def _set_admin(ctx: Context, value: bool, success: str) -> None:
    user_id = parse_positive_int(ctx.text)
    if user_id is None:
        await ctx.reply(texts.INVALID_NUMERIC_ID, buttons=keyboards.BACK)
    elif await ctx.app.container.users.set_admin(user_id, value):
        await ctx.go(State.ADMIN_PANEL)
        await ctx.reply(success, buttons=keyboards.ADMIN)
    else:
        await ctx.reply(texts.USER_NOT_FOUND, buttons=keyboards.BACK)


@router.text(Btn.LIST_ADMINS, admin=True, states=PANEL)
async def list_admins(ctx: Context) -> None:
    ids = await ctx.app.container.users.admin_ids()
    limit = asyncio.Semaphore(_ENTITY_CONCURRENCY)

    async def describe(user_id: int) -> str:
        async with limit:
            try:
                entity = await ctx.app.client.get_entity(user_id)
                name = getattr(entity, "first_name", None) or getattr(entity, "username", None) or "کاربر"
            except Exception:  # noqa: BLE001 - an unknown entity still gets listed
                name = "---"
        return texts.ADMIN_LIST_ITEM.format(name=name, user_id=user_id)

    lines = await asyncio.gather(*(describe(user_id) for user_id in ids))
    await ctx.reply(texts.ADMIN_LIST_TITLE + "".join(lines), buttons=keyboards.ADMIN)


# ---- statistics ----
@router.text(Btn.STATS, admin=True, states=PANEL)
async def stats(ctx: Context) -> None:
    await ctx.reply(texts.STATS.format(s=await ctx.app.container.stats.dashboard()), buttons=keyboards.ADMIN)


# ---- per-user access log ----
@router.text(Btn.USER_LOG, admin=True, states=PANEL)
async def ask_user_log(ctx: Context) -> None:
    await ctx.go(State.USER_LOG_ID)
    await ctx.reply(texts.ASK_USER_LOG_ID, buttons=keyboards.BACK)


@router.state(State.USER_LOG_ID, admin=True)
async def user_log(ctx: Context) -> None:
    user_id = parse_positive_int(ctx.text)
    if user_id is None:
        await ctx.reply(texts.INVALID_USER_ID, buttons=keyboards.BACK)
        return
    await ctx.go(State.ADMIN_PANEL)
    text, buttons = await _user_log_page(ctx.app, user_id, 0)
    await ctx.reply(text, buttons=buttons or keyboards.ADMIN)


@router.callback("userlog", admin=True)
async def user_log_page(ctx: CallbackContext) -> None:
    user_id, page = (int(arg) for arg in ctx.args)
    text, buttons = await _user_log_page(ctx.app, user_id, page)
    await ctx.event.edit(text, buttons=buttons)
    await ctx.event.answer()


async def _user_log_page(app: BotApp, user_id: int, page: int):
    profile = await app.container.users.profile(user_id)
    if profile is None:
        return texts.USER_LOG_UNKNOWN, None
    rows, total = await app.container.links.access_log(user_id, max(page, 0), LOG_PAGE_SIZE)
    if not total:
        return texts.USER_LOG_EMPTY.format(user_id=user_id), None
    pages = (total + LOG_PAGE_SIZE - 1) // LOG_PAGE_SIZE
    page = min(max(page, 0), pages - 1)
    lines = [
        texts.USER_LOG_TITLE.format(
            user_id=user_id, created=app.local_time(profile.created_at),
            active=app.local_time(profile.last_active_at) or texts.NONE,
            total=total, page=page + 1, pages=pages,
        ),
        *(
            texts.USER_LOG_ITEM.format(index=index, code=row.code, views=row.view_count,
                                       last_viewed=app.local_time(row.last_viewed))
            for index, row in enumerate(rows, start=page * LOG_PAGE_SIZE + 1)
        ),
    ]
    return "\n".join(lines), keyboards.pager(f"userlog:{user_id}", page, pages)
