"""Configuration: YAML file (no secrets) + environment variables (secrets)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

SCOPES = ("personal", "digisoft", "quokka", "rdim")
Scope = Literal["personal", "digisoft", "quokka", "rdim", "unsorted"]


class ConfigError(ValueError):
    pass


class ImapSource(BaseModel):
    id: str
    type: Literal["imap"]
    scopes: list[Scope] = Field(default_factory=lambda: ["unsorted"])  # type: ignore[arg-type]
    host: str
    port: int = 993
    ssl: bool = True
    username_env: str
    password_env: str
    folders: list[str] | None = None  # None: discover (Gmail: All Mail; others: all but junk/trash)
    exclude_folders: list[str] = Field(default_factory=list)
    poll_seconds: int = 60
    backfill_days: int = 365
    backfill_batch: int = 200  # messages per folder per cycle while backfilling

    def username(self) -> str:
        return _require_env(self.username_env, self.id)

    def password(self) -> str:
        return _require_env(self.password_env, self.id)


class TelegramChat(BaseModel):
    """One allowlisted chat: numeric id (as shown by `kb telegram chats`) or @username."""

    chat: int | str
    scopes: list[Scope] | None = None
    gap_minutes: int | None = None  # silence that starts a new conversation (default: source)

    def matches(self, chat_id: int, username: str | None) -> bool:
        if isinstance(self.chat, int):
            return self.chat == chat_id
        ref = self.chat.strip()
        if ref.lstrip("-").isdigit():
            return int(ref) == chat_id
        return bool(username) and ref.lstrip("@").lower() == (username or "").lower()


class TelegramSource(BaseModel):
    id: str
    type: Literal["telegram"]
    scopes: list[Scope] = Field(default_factory=lambda: ["unsorted"])  # type: ignore[arg-type]
    api_id_env: str = "TELEGRAM_API_ID"
    api_hash_env: str = "TELEGRAM_API_HASH"
    session_path: str = "/data/telegram/kb.session"
    chats: list[TelegramChat] = Field(default_factory=list)
    backfill_days: int = 365
    catch_up_seconds: int = 600
    gap_minutes: int = 45
    max_unit_messages: int = 100
    max_unit_hours: int = 12

    def api_id(self) -> int:
        value = _require_env(self.api_id_env, self.id)
        if not value.isdigit():
            raise ConfigError(f"source {self.id}: {self.api_id_env} must be a number")
        return int(value)

    def api_hash(self) -> str:
        return _require_env(self.api_hash_env, self.id)

    def chat_config(self, chat_id: int, username: str | None) -> TelegramChat | None:
        for c in self.chats:
            if c.matches(chat_id, username):
                return c
        return None

    def gap_for(self, chat_id: int, username: str | None) -> int:
        c = self.chat_config(chat_id, username)
        return c.gap_minutes if c and c.gap_minutes else self.gap_minutes

    def scopes_for(self, chat_id: int, username: str | None) -> list[str]:
        c = self.chat_config(chat_id, username)
        return list(c.scopes) if c and c.scopes else list(self.scopes)


Source = Annotated[ImapSource | TelegramSource, Field(discriminator="type")]


class ScopeRule(BaseModel):
    """Assign scopes to messages that match. Exactly one matcher must be set.

    address: sender or recipient email address · domain: email domain (subdomains too)
    chat: Telegram chat id or @username · folder: mail folder/label (optionally with `source`)
    """

    scopes: list[Scope]
    address: str | None = None
    domain: str | None = None
    chat: int | str | None = None
    folder: str | None = None
    source: str | None = None

    @field_validator("scopes")
    @classmethod
    def no_unsorted(cls, scopes: list[str]) -> list[str]:
        if not scopes or "unsorted" in scopes:
            raise ValueError("rule scopes must be one or more of personal, digisoft, quokka, rdim")
        return scopes

    def model_post_init(self, _: object) -> None:
        set_fields = [f for f in ("address", "domain", "chat", "folder") if getattr(self, f)]
        if len(set_fields) != 1:
            raise ValueError("a scope rule needs exactly one of: address, domain, chat, folder")


class Config(BaseModel):
    sources: list[Source] = Field(default_factory=list)
    scope_rules: list[ScopeRule] = Field(default_factory=list)

    @field_validator("sources")
    @classmethod
    def unique_ids(cls, sources: list[Source]) -> list[Source]:
        ids = [s.id for s in sources]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate source ids: {sorted(dupes)}")
        return sources

    def source(self, source_id: str) -> Source:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise ConfigError(f"unknown source {source_id!r}")

    def imap_sources(self) -> list[ImapSource]:
        return [s for s in self.sources if isinstance(s, ImapSource)]

    def telegram_sources(self) -> list[TelegramSource]:
        return [s for s in self.sources if isinstance(s, TelegramSource)]


def _require_env(name: str, source_id: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"source {source_id}: environment variable {name} is not set")
    return value


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Load from KB_CONFIG_YAML (inline YAML), else the file at `path` / KB_CONFIG."""
    inline = os.environ.get("KB_CONFIG_YAML")
    if inline and path is None:
        data = yaml.safe_load(inline)
    else:
        file = Path(path or os.environ.get("KB_CONFIG", "config/kb.yaml"))
        if not file.exists():
            raise ConfigError(f"config file {file} not found (or set KB_CONFIG_YAML)")
        data = yaml.safe_load(file.read_text())
    return Config.model_validate(data or {})


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ConfigError("DATABASE_URL is not set")
    return url
