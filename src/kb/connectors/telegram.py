"""Telegram connector: the owner's own account, read-only, allowlisted chats only.

Only read methods are reachable through `ReadOnlyClient`; nothing is sent, edited, deleted or
marked as read. Live updates come from Telethon events; `catch_up` fills gaps after downtime.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from kb.archive import RawRecord
from kb.config import ConfigError, TelegramSource
from kb.connectors.base import get_state, set_state, store
from kb.db import Conn

log = logging.getLogger(__name__)

PeerType = Literal["user", "group", "channel"]


class MessageReader(Protocol):
    def iter_messages(self, entity: Any, **kwargs: Any) -> AsyncIterator[Any]: ...


class ReadOnlyClient:
    """Exposes only the read methods of a Telethon client."""

    def __init__(self, client: Any) -> None:
        self.__client = client

    def iter_messages(self, entity: Any, **kwargs: Any) -> AsyncIterator[Any]:
        return self.__client.iter_messages(entity, **kwargs)

    def iter_dialogs(self) -> AsyncIterator[Any]:
        return self.__client.iter_dialogs()

    async def get_entity(self, ref: Any) -> Any:
        return await self.__client.get_entity(ref)


@dataclass(frozen=True)
class ChatInfo:
    chat_id: int
    title: str
    username: str | None
    peer_type: PeerType


def chat_info(entity: Any) -> ChatInfo:
    from telethon import utils

    cls = type(entity).__name__
    # Supergroups are Channels too and number messages per chat like channels do; users and
    # basic groups share one account-wide message numbering.
    peer: PeerType = "user" if cls == "User" else "channel" if cls == "Channel" else "group"
    return ChatInfo(
        chat_id=int(utils.get_peer_id(entity)),
        title=utils.get_display_name(entity) or str(getattr(entity, "id", "")),
        username=getattr(entity, "username", None),
        peer_type=peer,
    )


def _sender_name(msg: Any) -> str | None:
    sender = getattr(msg, "sender", None)
    if sender is None:
        return getattr(msg, "post_author", None)
    first = getattr(sender, "first_name", None) or ""
    last = getattr(sender, "last_name", None) or ""
    name = f"{first} {last}".strip() or getattr(sender, "title", None) or ""
    username = getattr(sender, "username", None)
    if username:
        name = f"{name} (@{username})".strip()
    return name or None


def _reactions(msg: Any) -> int:
    reactions = getattr(msg, "reactions", None)
    results = getattr(reactions, "results", None) or []
    return sum(int(getattr(r, "count", 0) or 0) for r in results)


def message_record(source_id: str, chat: ChatInfo, msg: Any) -> RawRecord:
    reply_to = getattr(msg, "reply_to", None)
    edit_date = getattr(msg, "edit_date", None)
    media = getattr(msg, "media", None)
    return RawRecord(
        source_id=source_id,
        external_id=f"{chat.chat_id}:{msg.id}",
        kind="tg_message",
        occurred_at=msg.date,
        payload={
            "chat_id": chat.chat_id,
            "chat_title": chat.title,
            "chat_username": chat.username,
            "peer_type": chat.peer_type,
            "msg_id": msg.id,
            "date": msg.date.isoformat(),
            "edit_date": edit_date.isoformat() if edit_date else None,
            "sender_id": getattr(msg, "sender_id", None),
            "sender_name": _sender_name(msg),
            "text": getattr(msg, "message", None) or "",
            "reply_to_msg_id": getattr(reply_to, "reply_to_msg_id", None),
            "topic_id": getattr(reply_to, "reply_to_top_id", None),
            "reactions": _reactions(msg),
            "media": type(media).__name__ if media is not None else None,
        },
    )


def deletion_record(source_id: str, chat_id: int | None, msg_ids: Iterable[int]) -> RawRecord:
    ids = sorted(int(i) for i in msg_ids)
    return RawRecord(
        source_id=source_id,
        external_id=f"delete:{chat_id}:{','.join(map(str, ids))}",
        kind="tg_delete",
        occurred_at=datetime.now(UTC),
        payload={"chat_id": chat_id, "msg_ids": ids},
    )


def _state_key(chat_id: int) -> str:
    return f"chat:{chat_id}"


def _remember_last_id(conn: Conn, source_id: str, chat_id: int, msg_id: int) -> None:
    state = get_state(conn, source_id, _state_key(chat_id)) or {}
    if msg_id > int(state.get("last_id", 0)):
        set_state(conn, source_id, _state_key(chat_id), {"last_id": msg_id})


def on_message(conn: Conn, source: TelegramSource, chat: ChatInfo, msg: Any) -> bool:
    """New or edited message. Returns True if something new was archived."""
    if source.chat_config(chat.chat_id, chat.username) is None:
        return False
    stored = store(conn, message_record(source.id, chat, msg))
    _remember_last_id(conn, source.id, chat.chat_id, msg.id)
    return stored


def on_deleted(conn: Conn, source: TelegramSource, chat_id: int | None, msg_ids: list[int]) -> bool:
    """Deletion event. Private-chat deletions arrive without a chat id; the indexer only hides
    items already stored, so archiving the event never adds content from other chats."""
    return store(conn, deletion_record(source.id, chat_id, msg_ids))


async def catch_up(
    conn: Conn,
    client: MessageReader,
    source: TelegramSource,
    entities: list[Any],
    now: datetime | None = None,
) -> int:
    """Fetch messages missed since the last seen id (or the backfill window on first run)."""
    stored = 0
    since = (now or datetime.now(UTC)) - timedelta(days=source.backfill_days)
    for entity in entities:
        chat = chat_info(entity)
        state = get_state(conn, source.id, _state_key(chat.chat_id))
        if state is None:
            messages = client.iter_messages(entity, offset_date=since, reverse=True)
        else:
            messages = client.iter_messages(entity, min_id=int(state["last_id"]), reverse=True)
        async for msg in messages:
            if msg.date < since:
                continue
            if on_message(conn, source, chat, msg):
                stored += 1
        log.info("telegram %s: caught up %s", source.id, chat.title)
    return stored


async def resolve_chats(client: ReadOnlyClient, source: TelegramSource) -> list[Any]:
    entities = []
    for c in source.chats:
        ref: Any = c.chat
        if isinstance(ref, str) and ref.lstrip("-").isdigit():
            ref = int(ref)
        try:
            entities.append(await client.get_entity(ref))
        except (ValueError, TypeError) as exc:
            log.error("telegram %s: cannot resolve chat %r: %s", source.id, c.chat, exc)
    return entities


def make_client(source: TelegramSource) -> Any:
    from telethon import TelegramClient

    return TelegramClient(
        source.session_path, source.api_id(), source.api_hash(), flood_sleep_threshold=120
    )


async def run(source: TelegramSource, connect_db: Callable[[], Conn]) -> None:
    """Long-running ingest: catch up, then follow live events; re-check gaps periodically."""
    from telethon import events

    raw = make_client(source)
    await raw.connect()
    if not await raw.is_user_authorized():
        raise ConfigError(
            f"telegram source {source.id}: not logged in; run `kb auth telegram {source.id}`"
        )
    client = ReadOnlyClient(raw)
    conn = connect_db()
    entities = await resolve_chats(client, source)
    by_id = {chat_info(e).chat_id: e for e in entities}

    @raw.on(events.NewMessage(chats=list(by_id)))
    async def _new(event: Any) -> None:
        on_message(conn, source, chat_info(by_id[event.chat_id]), event.message)

    @raw.on(events.MessageEdited(chats=list(by_id)))
    async def _edited(event: Any) -> None:
        on_message(conn, source, chat_info(by_id[event.chat_id]), event.message)

    @raw.on(events.MessageDeleted())
    async def _deleted(event: Any) -> None:
        chat_id = event.chat_id
        if chat_id is not None and chat_id not in by_id:
            return
        on_deleted(conn, source, chat_id, list(event.deleted_ids))

    await catch_up(conn, client, source, entities)

    async def periodic() -> None:
        while True:
            await asyncio.sleep(source.catch_up_seconds)
            try:
                await catch_up(conn, client, source, entities)
            except Exception:
                log.exception("telegram %s: periodic catch-up failed", source.id)

    task = asyncio.create_task(periodic())
    try:
        await raw.run_until_disconnected()
    finally:
        task.cancel()
