"""Conversation state machine enumeration."""

from __future__ import annotations

from enum import Enum, auto


class State(Enum):
    """Enumerates every supported user interaction state."""

    USER_UPLOAD_FILE = auto()
    USER_DELETE_FILE = auto()
    USER_SEND_ID_FOR_SET_CAPTION = auto()
    USER_SEND_TEXT_FOR_SET_CAPTION = auto()
    USER_SEND_ID_FOR_UNSET_CAPTION = auto()
    USER_SEND_ID_FOR_SET_PASSWORD = auto()
    USER_SEND_TEXT_FOR_SET_PASSWORD = auto()
    USER_SEND_ID_FOR_UNSET_PASSWORD = auto()
    USER_SEND_PASSWORD_FOR_GET_FILE = auto()
    USER_SEND_ID_FILE_FOR_TRACKING = auto()
    USER_ADMIN_PANEL = auto()
    USER_SET_ADMIN = auto()
    USER_UNSET_ADMIN = auto()
    USER_FORWARD_MESSAGE_FOR_ALL = auto()
    USER_SEND_MESSAGE_FOR_ALL = auto()
    USER_JOIN_CHANNEL_PANEL = auto()
    USER_ADD_CHANNEL = auto()
    USER_REMOVE_CHANNEL = auto()

