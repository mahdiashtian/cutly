from __future__ import annotations

from schemas.base import BaseDTO


def chat_peer(ref: str) -> int | str:
    """What Telethon accepts: an int for ``-100…`` ids, the username otherwise."""
    ref = ref.strip()
    return int(ref) if ref.lstrip("-").isdigit() else ref


class ChannelDTO(BaseDTO):
    id: int
    chat_ref: str
    invite_link: str
    title: str

    @property
    def peer(self) -> int | str:
        return chat_peer(self.chat_ref)
