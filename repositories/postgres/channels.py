from __future__ import annotations

from sqlalchemy import delete, or_, select, update

from db.models import MandatoryChannel
from repositories.postgres.base import SqlRepository
from schemas.channel import ChannelDTO


class ChannelRepository(SqlRepository):
    async def list_all(self) -> list[ChannelDTO]:
        rows = await self._session.scalars(select(MandatoryChannel).order_by(MandatoryChannel.id))
        return [ChannelDTO.model_validate(row) for row in rows]

    async def add(self, *, chat_ref: str, invite_link: str, title: str) -> ChannelDTO:
        channel = MandatoryChannel(chat_ref=chat_ref, invite_link=invite_link, title=title)
        self._session.add(channel)
        await self._session.flush()
        return ChannelDTO.model_validate(channel)

    async def delete(self, identifier: str) -> bool:
        """Admins may paste either the id/username or the invite link."""
        result = await self._session.execute(
            delete(MandatoryChannel).where(
                or_(MandatoryChannel.chat_ref == identifier, MandatoryChannel.invite_link == identifier)
            )
        )
        return bool(result.rowcount)

    async def set_title(self, channel_id: int, title: str) -> None:
        await self._session.execute(
            update(MandatoryChannel).where(MandatoryChannel.id == channel_id).values(title=title)
        )
