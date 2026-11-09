"""Conversation states and where «🔙 بازگشت» leads from each one.

The member *name* is what gets stored in Redis; renaming a member only resets
conversations that were in it (they fall back to IDLE).
"""
from __future__ import annotations

from enum import Enum, auto


class State(Enum):
    IDLE = auto()
    # ---- upload ----
    UPLOADING = auto()
    UPLOAD_LIMITS = auto()
    # ---- managing own links (each asks for a code first) ----
    DELETE_CODE = auto()
    CAPTION_CODE = auto()
    CAPTION_TEXT = auto()
    CAPTION_REMOVE_CODE = auto()
    PASSWORD_CODE = auto()
    PASSWORD_TEXT = auto()
    PASSWORD_REMOVE_CODE = auto()
    TRACK_CODE = auto()
    # ---- downloading a protected link ----
    LINK_PASSWORD = auto()
    # ---- admin ----
    ADMIN_PANEL = auto()
    ADMIN_ADD = auto()
    ADMIN_REMOVE = auto()
    USER_LOG_ID = auto()
    JOIN_PANEL = auto()
    CHANNEL_ADD = auto()
    CHANNEL_REMOVE = auto()
    CAPTION_PANEL = auto()
    GLOBAL_CAPTION_TEXT = auto()
    BROADCAST_CONTENT = auto()
    BROADCAST_AUDIENCE = auto()
    BROADCAST_CHANNEL = auto()
    BROADCAST_CONFIRM = auto()
    BROADCAST_SCHEDULE = auto()
    RESTORE_UPLOAD = auto()
    RESTORE_WAITING = auto()
    RESTORE_CONFIRM = auto()


ADMIN_STATES = frozenset({
    State.ADMIN_PANEL, State.ADMIN_ADD, State.ADMIN_REMOVE, State.USER_LOG_ID,
    State.JOIN_PANEL, State.CHANNEL_ADD, State.CHANNEL_REMOVE,
    State.CAPTION_PANEL, State.GLOBAL_CAPTION_TEXT,
    State.BROADCAST_CONTENT, State.BROADCAST_AUDIENCE, State.BROADCAST_CHANNEL,
    State.BROADCAST_CONFIRM, State.BROADCAST_SCHEDULE,
    State.RESTORE_UPLOAD, State.RESTORE_WAITING, State.RESTORE_CONFIRM,
})

# Sub-panels go back to their panel; every other admin state to the admin
# panel; everything else to the main menu (IDLE).
_PARENTS = {
    State.CHANNEL_ADD: State.JOIN_PANEL,
    State.CHANNEL_REMOVE: State.JOIN_PANEL,
    State.GLOBAL_CAPTION_TEXT: State.CAPTION_PANEL,
    State.UPLOAD_LIMITS: State.UPLOADING,
}


def parent_of(state: State) -> State:
    if state in _PARENTS:
        return _PARENTS[state]
    return State.ADMIN_PANEL if state in ADMIN_STATES else State.IDLE
