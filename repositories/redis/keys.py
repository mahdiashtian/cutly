"""Every Redis key the application uses, in one place.

Three tiers, each with its own prefix, so each can be treated differently:

* ``cutly:cache:v1:*`` — disposable copies of SQL rows. Safe to flush at any time
  (and flushed after a restore); bump ``v1`` when a cached DTO changes shape.
* ``cutly:state:*`` — data that exists nowhere else (conversations, upload
  sessions, a staged restore, the maintenance flag). Never flushed by the cache.
* ``cutly:ops:*`` — short-lived markers with their own TTL (throttles).
"""
from __future__ import annotations

PREFIX = "cutly"
CACHE_NAMESPACE = f"{PREFIX}:cache:v1"
STATE_NAMESPACE = f"{PREFIX}:state"
OPS_NAMESPACE = f"{PREFIX}:ops"


# ---- cache tier ----
def cache_pattern() -> str:
    return f"{CACHE_NAMESPACE}:*"


def user(user_id: int) -> str:
    return f"{CACHE_NAMESPACE}:user:{user_id}"


def link(code: str) -> str:
    return f"{CACHE_NAMESPACE}:link:{code}"


def mandatory_channels() -> str:
    return f"{CACHE_NAMESPACE}:channels"


def settings() -> str:
    return f"{CACHE_NAMESPACE}:settings"


def joined_channels(user_id: int) -> str:
    """Positive-only "member of every mandatory channel" marker."""
    return f"{CACHE_NAMESPACE}:joined:{user_id}"


# ---- state tier ----
def conversation(user_id: int) -> str:
    return f"{STATE_NAMESPACE}:conversation:{user_id}"


def conversation_pattern() -> str:
    return f"{STATE_NAMESPACE}:conversation:*"


def upload_session(user_id: int) -> str:
    return f"{STATE_NAMESPACE}:upload:{user_id}"


def upload_session_pattern() -> str:
    return f"{STATE_NAMESPACE}:upload:*"


def staged_restore(admin_id: int) -> str:
    return f"{STATE_NAMESPACE}:restore:{admin_id}"


def maintenance() -> str:
    return f"{STATE_NAMESPACE}:maintenance"


# ---- ops tier ----
def activity_touch(user_id: int) -> str:
    return f"{OPS_NAMESPACE}:activity:{user_id}"


def rate_limit(name: str, key: str | int) -> str:
    return f"{OPS_NAMESPACE}:rate:{name}:{key}"
