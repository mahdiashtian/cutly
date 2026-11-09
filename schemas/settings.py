from __future__ import annotations

from schemas.base import BaseDTO


class BotSettingsDTO(BaseDTO):
    global_caption: str | None = None
    show_file_captions: bool = True

    def caption_for(self, own_caption: str | None) -> str:
        """The global caption leads; a link's own caption follows when enabled."""
        own = own_caption if self.show_file_captions else None
        return "\n".join(part for part in (self.global_caption, own) if part)
