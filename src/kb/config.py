"""Configuration: YAML file (no secrets) + environment variables (secrets)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

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
    folders: list[str] = Field(default_factory=lambda: ["INBOX"])
    poll_seconds: int = 60
    backfill_days: int = 365

    def username(self) -> str:
        return _require_env(self.username_env, self.id)

    def password(self) -> str:
        return _require_env(self.password_env, self.id)


class Config(BaseModel):
    sources: list[ImapSource] = Field(default_factory=list)

    @field_validator("sources")
    @classmethod
    def unique_ids(cls, sources: list[ImapSource]) -> list[ImapSource]:
        ids = [s.id for s in sources]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate source ids: {sorted(dupes)}")
        return sources

    def source(self, source_id: str) -> ImapSource:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise ConfigError(f"unknown source {source_id!r}")


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
