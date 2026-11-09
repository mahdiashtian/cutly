from __future__ import annotations

from sqlalchemy import select, update

from db.models import SETTINGS_ROW_ID, BotSettings
from repositories.postgres.base import SqlRepository
from schemas.settings import BotSettingsDTO


class SettingsRepository(SqlRepository):
    async def get(self) -> BotSettingsDTO:
        row = await self._session.scalar(select(BotSettings).where(BotSettings.id == SETTINGS_ROW_ID))
        return BotSettingsDTO.model_validate(row) if row else BotSettingsDTO()

    async def update(self, **values) -> BotSettingsDTO:
        """Upsert the singleton row, so a fresh database needs no seeding step."""
        await self._session.execute(
            self._insert(BotSettings.__table__)
            .values(id=SETTINGS_ROW_ID, show_file_captions=True)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await self._session.execute(
            update(BotSettings).where(BotSettings.id == SETTINGS_ROW_ID).values(**values)
        )
        return await self.get()
