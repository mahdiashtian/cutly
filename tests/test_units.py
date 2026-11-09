from __future__ import annotations

from types import SimpleNamespace

from telethon.errors import UserNotParticipantError
from telethon.tl.custom.message import Message
from telethon.tl.types import (
    Document,
    DocumentAttributeAnimated,
    DocumentAttributeAudio,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    InputStickerSetEmpty,
    MessageMediaDocument,
    MessageMediaPhoto,
    PeerUser,
    Photo,
    PhotoSize,
)

from bot.keyboards import Btn
from bot.media import extract_media
from bot.membership import MembershipGuard
from bot.router import Access, Router
from bot.states import State, parent_of
from core.enums import MediaType


def _document(*attributes) -> Message:
    document = Document(id=7, access_hash=8, file_reference=b"r", date=None, mime_type="x", size=99,
                        dc_id=1, attributes=list(attributes))
    return Message(id=1, peer_id=PeerUser(1), media=MessageMediaDocument(document=document))


def test_media_classification():
    photo = Photo(id=5, access_hash=6, file_reference=b"p", date=None, dc_id=1,
                  sizes=[PhotoSize(type="x", w=1, h=1, size=777)])
    ref = extract_media(Message(id=1, peer_id=PeerUser(1), media=MessageMediaPhoto(photo=photo)))
    assert (ref.media_type, ref.size, ref.file_id, ref.file_reference) == (MediaType.PHOTO, 777, 5, b"p")

    video = DocumentAttributeVideo(duration=1, w=1, h=1)
    assert extract_media(_document(video)).media_type is MediaType.VIDEO
    assert extract_media(_document(DocumentAttributeAnimated(), video)).media_type is MediaType.ANIMATION
    assert extract_media(_document(DocumentAttributeAudio(duration=1, voice=True))).media_type is MediaType.VOICE
    assert extract_media(_document(DocumentAttributeAudio(duration=1))).media_type is MediaType.AUDIO
    assert extract_media(_document()).media_type is MediaType.DOCUMENT
    sticker = DocumentAttributeSticker(alt="", stickerset=InputStickerSetEmpty())
    assert extract_media(_document(sticker)) is None
    assert extract_media(Message(id=1, peer_id=PeerUser(1), message="text")) is None


def test_router_prefers_state_scoped_routes_and_ignores_misplaced_labels():
    router = Router()

    @router.text("x")
    async def anywhere(ctx): ...

    @router.text("x", states={State.UPLOADING})
    async def while_uploading(ctx): ...

    @router.text("only-admin-panel", access=Access.ADMIN, states={State.ADMIN_PANEL})
    async def panel(ctx): ...

    @router.state(State.CAPTION_TEXT)
    async def caption(ctx): ...

    assert router.resolve("x", State.UPLOADING).handler is while_uploading
    assert router.resolve("x", State.IDLE).handler is anywhere
    assert router.resolve("only-admin-panel", State.CAPTION_TEXT) is None  # known label, wrong place
    assert router.resolve("free text", State.CAPTION_TEXT).handler is caption
    assert router.resolve("free text", State.IDLE) is None


def test_long_captions_are_trimmed_but_keep_the_footer():
    from bot.handlers.download import CAPTION_LIMIT, fit_caption

    footer = "\n👁 تعداد دانلود : 1"
    assert fit_caption("short", footer) == "short" + footer
    fitted = fit_caption("😀" * 2000, footer)
    assert fitted.endswith("…" + footer)
    assert len(fitted.encode("utf-16-le")) // 2 <= CAPTION_LIMIT


def test_back_navigation_map():
    assert parent_of(State.CHANNEL_ADD) is State.JOIN_PANEL
    assert parent_of(State.UPLOAD_LIMITS) is State.UPLOADING
    assert parent_of(State.BROADCAST_CONFIRM) is State.ADMIN_PANEL
    assert parent_of(State.ADMIN_PANEL) is State.ADMIN_PANEL
    assert parent_of(State.CAPTION_TEXT) is State.IDLE
    assert Btn.BACK == "🔙 بازگشت"


async def test_membership_is_cached_only_when_positive(container):
    await container.channels.add(chat_ref="news", invite_link="https://t.me/news", title="News")
    calls = []

    async def get_permissions(peer, user_id):
        calls.append(user_id)
        if user_id == 2:
            raise UserNotParticipantError(request=None)
        if user_id == 3:
            raise RuntimeError("telegram unavailable")

    guard = MembershipGuard(container, SimpleNamespace(get_permissions=get_permissions))
    assert await guard.missing_channels(1) == []
    assert await guard.missing_channels(1) == []  # served from the positive marker
    assert calls == [1]
    assert [c.chat_ref for c in await guard.missing_channels(2)] == ["news"]
    assert [c.chat_ref for c in await guard.missing_channels(3)] == ["news"]  # errors fail closed
    await guard.missing_channels(2)
    assert calls.count(2) == 2  # a negative answer is never cached

    # Changing the channel set invalidates every positive marker at once.
    await container.channels.add(chat_ref="more", invite_link="https://t.me/more", title="More")
    await guard.missing_channels(1)
    assert calls.count(1) == 3
