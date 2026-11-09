"""Admin: the global caption shown under every delivered file."""
from __future__ import annotations

from bot import keyboards, texts
from bot.handlers.menus import caption_menu
from bot.keyboards import Btn
from bot.router import Access, Context, Router
from bot.states import State

router = Router()
PANEL = {State.CAPTION_PANEL}


@router.text(Btn.CAPTION_PANEL, access=Access.ADMIN, states={State.ADMIN_PANEL})
async def open_panel(ctx: Context) -> None:
    await caption_menu(ctx)


@router.text(Btn.SET_GLOBAL_CAPTION, access=Access.ADMIN, states=PANEL)
async def ask_caption(ctx: Context) -> None:
    await ctx.go(State.GLOBAL_CAPTION_TEXT)
    await ctx.reply(texts.ASK_GLOBAL_CAPTION, buttons=keyboards.BACK)


@router.state(State.GLOBAL_CAPTION_TEXT, access=Access.ADMIN)
async def set_caption(ctx: Context) -> None:
    await ctx.app.container.settings_service.set_global_caption(ctx.text)
    await ctx.reply(texts.GLOBAL_CAPTION_SET)
    await caption_menu(ctx)


@router.text(Btn.UNSET_GLOBAL_CAPTION, access=Access.ADMIN, states=PANEL)
async def unset_caption(ctx: Context) -> None:
    await ctx.app.container.settings_service.set_global_caption(None)
    await ctx.reply(texts.GLOBAL_CAPTION_REMOVED)
    await caption_menu(ctx)


@router.text(Btn.TOGGLE_FILE_CAPTIONS, access=Access.ADMIN, states=PANEL)
async def toggle_file_captions(ctx: Context) -> None:
    await ctx.app.container.settings_service.toggle_file_captions()
    await caption_menu(ctx)
