"""Opening a menu = moving to its state + sending its keyboard. Shared by the
handlers that open a menu and by «🔙 بازگشت»."""
from __future__ import annotations

from bot import keyboards, texts
from bot.router import Context
from bot.states import State

MAX_CODE_LENGTH = 32


async def main_menu(ctx: Context) -> None:
    await ctx.go(State.IDLE)
    await ctx.app.container.uploads.clear(ctx.user_id)
    await ctx.reply(texts.START.format(name=await ctx.first_name()), buttons=keyboards.MAIN)


async def admin_menu(ctx: Context) -> None:
    await ctx.go(State.ADMIN_PANEL)
    await ctx.reply(texts.ADMIN_PANEL.format(name=await ctx.first_name()), buttons=keyboards.ADMIN)


async def join_menu(ctx: Context) -> None:
    await ctx.go(State.JOIN_PANEL)
    await ctx.reply(texts.JOIN_PANEL.format(name=await ctx.first_name()), buttons=keyboards.JOIN_PANEL)


async def caption_menu(ctx: Context) -> None:
    await ctx.go(State.CAPTION_PANEL)
    settings = await ctx.app.container.settings_service.get()
    await ctx.reply(
        texts.CAPTION_PANEL.format(
            name=await ctx.first_name(),
            caption=settings.global_caption or texts.CAPTION_UNSET,
            status=texts.CAPTION_ON if settings.show_file_captions else texts.CAPTION_OFF,
        ),
        buttons=keyboards.CAPTION_PANEL,
    )


async def upload_menu(ctx: Context) -> None:
    await ctx.go(State.UPLOADING)
    await ctx.reply(texts.UPLOAD_STILL_OPEN, buttons=keyboards.UPLOAD_SESSION)


MENUS = {
    State.IDLE: main_menu,
    State.ADMIN_PANEL: admin_menu,
    State.JOIN_PANEL: join_menu,
    State.CAPTION_PANEL: caption_menu,
    State.UPLOADING: upload_menu,
}


def valid_code(text: str) -> str | None:
    code = text.strip()
    return code if 0 < len(code) <= MAX_CODE_LENGTH else None


def parse_positive_int(text: str) -> int | None:
    try:
        value = int(text.strip())
    except ValueError:
        return None
    return value if value > 0 else None
