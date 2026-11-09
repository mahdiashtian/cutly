"""/start, «🔙 بازگشت», account, creator and the idle fallback."""
from __future__ import annotations

from bot import keyboards, texts
from bot.handlers import download
from bot.handlers.backups import discard_staged_restore
from bot.handlers.menus import MENUS, main_menu
from bot.keyboards import Btn
from bot.router import Context, Router
from bot.states import State, parent_of

router = Router()


@router.text("/start")
async def start(ctx: Context) -> None:
    if ctx.args.startswith("get_"):
        await ctx.go(State.IDLE)
        await download.open_link(ctx, ctx.args.removeprefix("get_"))
    else:
        await main_menu(ctx)


@router.text(Btn.BACK)
async def back(ctx: Context) -> None:
    await discard_staged_restore(ctx)
    await MENUS[parent_of(ctx.state)](ctx)


@router.text(Btn.ACCOUNT)
async def account(ctx: Context) -> None:
    sender = await ctx.event.get_sender()
    links = await ctx.app.container.links.count_owned(ctx.user_id)
    await ctx.reply(
        texts.ACCOUNT.format(links=links, name=await ctx.first_name(),
                             username=getattr(sender, "username", None) or "-----", bot=ctx.app.username),
        buttons=keyboards.MAIN,
    )


@router.text(Btn.CREATOR)
async def creator(ctx: Context) -> None:
    await ctx.reply(texts.CREATOR.format(username=ctx.app.settings.creator_username), buttons=keyboards.MAIN)


@router.state(State.IDLE)
async def idle(ctx: Context) -> None:
    """Anything typed outside a flow shows the main menu."""
    await main_menu(ctx)
