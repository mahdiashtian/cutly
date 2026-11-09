from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaseDTO(BaseModel):
    """Immutable data passed between layers and stored in the cache as JSON.

    * ``from_attributes`` builds a DTO straight from an ORM row.
    * bytes (Telegram file references) round-trip through JSON as base64.
    * ``frozen`` stops a handler from mutating a value another caller shares.
    """

    model_config = ConfigDict(
        from_attributes=True, frozen=True, ser_json_bytes="base64", val_json_bytes="base64"
    )
