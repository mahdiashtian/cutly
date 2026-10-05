from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from telethon import types
from services import read_file_from_db, set_global_caption, set_show_file_captions
from utils.helpers import build_file_caption, send_file


@pytest.mark.parametrize(
    "global_caption,file_caption,show,expected",
    [
        (None, None, True, ""),
        ("global", "local", True, "global\nlocal"),
        ("global", "local", False, "global"),
        (None, "local", True, "local"),
        (None, "local", False, ""),
        ("", "", True, ""),
    ],
)
def test_caption_composition(global_caption, file_caption, show, expected):
    settings = SimpleNamespace(global_caption=global_caption, show_file_captions=show)
    assert build_file_caption(file_caption, settings) == expected


@pytest.mark.parametrize(
    "media_type,expected",
    [
        ("photo", types.InputPhoto),
        ("video", types.InputDocument),
        ("voice", types.InputDocument),
        ("audio", types.InputDocument),
        ("document", types.InputDocument),
    ],
)
async def test_single_file_direct_ids_caption_and_count(
    make_file, telegram, media_type, expected
):
    file = await make_file(type=media_type, caption="local")
    await set_global_caption("global")
    sent = await send_file(
        telegram, 100, file, bot_username="bot", keyboard=[], storage_channel_id=-100
    )
    call = telegram.send_file.call_args
    assert isinstance(call.kwargs["file"], expected)
    assert call.kwargs["file"].id == file.file_id
    assert call.kwargs["caption"].startswith("global\nlocal")
    assert "۳۰" in call.kwargs["caption"] and "@bot" in call.kwargs["caption"]
    assert len(sent) == 1 and (await read_file_from_db(file.code)).count == 1


async def test_failed_single_delivery_does_not_count(make_file, telegram):
    file = await make_file()
    telegram.send_file.side_effect = ValueError("failed")
    with pytest.raises(ValueError):
        await send_file(
            telegram,
            100,
            file,
            bot_username="bot",
            keyboard=[],
            storage_channel_id=-100,
        )
    assert (await read_file_from_db(file.code)).count == 0


async def test_mixed_album_repeats_caption_on_every_item(make_file, telegram):
    first = await make_file("album", album_id="group", album_order=0, caption="local")
    await make_file("album_part1", album_id="group", album_order=1, type="video")
    await make_file("album_part2", album_id="group", album_order=2, type="voice")
    await set_global_caption("global")
    telegram.send_file.side_effect = [
        [SimpleNamespace(id=1), SimpleNamespace(id=2)],
        SimpleNamespace(id=3),
    ]
    sent = await send_file(
        telegram, 100, first, bot_username="bot", keyboard=[], storage_channel_id=-100
    )
    album_call, voice_call = telegram.send_file.call_args_list
    assert len(sent) == 3
    assert len(album_call.kwargs["caption"]) == 2
    assert all(c.startswith("global\nlocal") for c in album_call.kwargs["caption"])
    assert voice_call.kwargs["caption"] == album_call.kwargs["caption"][0]
    from services.file import read_album_files

    assert [f.count for f in await read_album_files("group")] == [1, 1, 1]


async def test_group_failure_falls_back_to_individual_items(make_file, telegram):
    first = await make_file("album", album_id="group", album_order=0)
    await make_file("album_part1", album_id="group", album_order=1)
    telegram.send_file.side_effect = [
        ValueError("album rejected"),
        SimpleNamespace(id=1),
        SimpleNamespace(id=2),
    ]
    sent = await send_file(
        telegram, 100, first, bot_username="bot", keyboard=[], storage_channel_id=-100
    )
    assert [m.id for m in sent] == [1, 2]
    assert all(call.kwargs["caption"] for call in telegram.send_file.call_args_list)
