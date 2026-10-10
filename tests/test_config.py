from pathlib import Path

import pytest

from kb.config import ConfigError, load_config


def test_example_config_is_valid(monkeypatch):
    monkeypatch.delenv("KB_CONFIG_YAML", raising=False)
    config = load_config(Path("config/kb.example.yaml"))
    assert config.sources[0].id == "mail-main"


def test_inline_yaml_wins(monkeypatch):
    monkeypatch.setenv("KB_CONFIG_YAML", "sources: []")
    assert load_config().sources == []


def test_missing_credential_env_is_named(monkeypatch):
    monkeypatch.delenv("KB_CONFIG_YAML", raising=False)
    monkeypatch.delenv("IMAP_PASSWORD_MAIN", raising=False)
    source = load_config(Path("config/kb.example.yaml")).sources[0]
    with pytest.raises(ConfigError, match="IMAP_PASSWORD_MAIN"):
        source.password()
